"""
Configuración EFECTIVA del motor de IA.

Dos fuentes, en este orden de prioridad:
  1. Interfaz de administración: la fila vigente de la tabla `llm_config`
     (la elige el Administrador del Sistema, queda auditada y la clave va cifrada).
  2. Archivo .env del servidor (LLM_PROVIDER + variables LLM_* / por proveedor).

Si la fila de la BD no se puede leer (p.ej. la migración 003 aún no se aplicó) o
apunta a un proveedor que el servidor ya no permite, se usa el .env y se deja
una advertencia en el log: nunca se cae en silencio a OTRO proveedor.

El worker relee la BD como máximo cada LLM_CONFIG_CACHE_S segundos, así que un
cambio hecho en la interfaz se aplica a la siguiente generación sin reiniciar.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..config import settings
from . import catalogo

logger = logging.getLogger(__name__)


MODOS_SINTESIS = ("auto", "completa", "secciones")


class ConfigIAError(ValueError):
    """Configuración del motor de IA inválida (proveedor desconocido, falta URL, etc.)."""


@dataclass
class Ajustes:
    proveedor: str
    etiqueta: str
    adaptador: str
    resguardo: str
    modelo: str
    base_url: str
    api_key: str = field(repr=False)
    json_mode: bool
    temperature: float | None
    token_param: str
    extra_params: dict[str, Any]
    timeout_s: float
    max_output_tokens: int
    max_output_techo: int
    context_tokens: int
    max_retries: int
    origen: str  # "env" | "ui"
    sintesis_modo: str = "auto"  # auto | completa | secciones

    def publico(self) -> dict[str, Any]:
        """Vista segura para la API/la interfaz: NUNCA incluye la clave."""
        d = asdict(self)
        clave = d.pop("api_key") or ""
        d["api_key_configurada"] = bool(clave)
        d["api_key_sufijo"] = clave[-4:] if len(clave) >= 8 else ""
        d["host"] = urlparse(self.base_url).hostname or ""
        return d

    def firma(self) -> str:
        """Identificador corto para auditoría y trazabilidad: 'proveedor/modelo'."""
        return f"{self.proveedor}/{self.modelo}"


# ---------------------------------------------------------------------------
#  Helpers de parseo
# ---------------------------------------------------------------------------
def _parse_temperature(valor: Any, defecto: float | None) -> float | None:
    if valor is None or valor == "":
        return defecto
    if isinstance(valor, str) and valor.strip().lower() in ("none", "null", "omitir"):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError) as e:
        raise ConfigIAError(f"LLM_TEMPERATURE inválida: {valor!r}") from e


def _parse_extra(valor: Any) -> dict[str, Any] | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, dict):
        return valor
    try:
        data = json.loads(valor)
    except json.JSONDecodeError as e:
        raise ConfigIAError(f"LLM_EXTRA_PARAMS no es JSON válido: {e}") from e
    if not isinstance(data, dict):
        raise ConfigIAError("LLM_EXTRA_PARAMS debe ser un objeto JSON, p.ej. {\"reasoning_effort\":\"none\"}")
    return data


def permitidos() -> set[str]:
    """Proveedores habilitados en este servidor (vacío en .env = todos)."""
    crudo = (settings.llm_proveedores_permitidos or "").strip()
    if not crudo:
        return set(catalogo.nombres())
    return {p.strip().lower() for p in crudo.split(",") if p.strip()}


def _explicito(campo: str) -> bool:
    """True si la variable se definió de verdad en el entorno/.env (no es el default)."""
    return campo in settings.model_fields_set


# ---------------------------------------------------------------------------
#  Construcción
# ---------------------------------------------------------------------------
def construir(proveedor: str, cambios: dict[str, Any] | None = None, *, origen: str) -> Ajustes:
    """Arma los ajustes partiendo del preset del proveedor y aplicando `cambios`."""
    nombre = (proveedor or "").strip().lower()
    presets = catalogo.presets()
    if nombre not in presets:
        raise ConfigIAError(
            f"Proveedor de IA desconocido: {proveedor!r}. Valores válidos: {', '.join(presets)}"
        )
    p = presets[nombre]
    c = {k: v for k, v in (cambios or {}).items() if v is not None and v != ""}

    modelo = str(c.get("modelo") or p.modelo).strip()
    extra = _parse_extra(c.get("extra_params"))
    techo = int(c.get("max_output_techo") or 0) or p.max_output_techo or settings.llm_max_output_tokens
    ctx = int(c.get("context_tokens") or settings.llm_context_tokens or 0)
    salida = settings.llm_max_output_tokens
    if ctx:
        # Con la ventana declarada, la salida no puede comerse toda la entrada.
        salida = max(512, min(salida, int(ctx * 0.45)))
        techo = min(techo, int(ctx * 0.6))
    techo = max(techo, salida)

    aj = Ajustes(
        proveedor=nombre,
        etiqueta=p.etiqueta,
        adaptador=p.adaptador,
        resguardo=p.resguardo,
        modelo=modelo,
        base_url=str(c.get("base_url") or p.base_url).strip(),
        api_key=str(c.get("api_key") or p.api_key).strip(),
        json_mode=bool(c["json_mode"]) if "json_mode" in c else p.json_mode,
        temperature=_parse_temperature(c.get("temperature"), p.temperature),
        token_param=str(c.get("token_param") or p.token_param),
        extra_params=extra if extra is not None else catalogo.extra_por_defecto(p, modelo),
        timeout_s=float(c.get("timeout_s") or settings.llm_timeout_s),
        max_output_tokens=salida,
        max_output_techo=techo,
        context_tokens=ctx,
        max_retries=settings.llm_max_retries,
        origen=origen,
        sintesis_modo=str(c.get("sintesis_modo") or settings.llm_sintesis_modo or "auto").strip().lower(),
    )
    validar(aj, requiere_clave=p.requiere_api_key)
    return aj


def validar(aj: Ajustes, *, requiere_clave: bool = True) -> None:
    if aj.token_param not in ("max_tokens", "max_completion_tokens"):
        raise ConfigIAError("LLM_TOKEN_PARAM debe ser max_tokens o max_completion_tokens")
    if not aj.modelo:
        raise ConfigIAError(f"Falta el modelo para el proveedor '{aj.proveedor}' (LLM_MODEL)")
    if aj.adaptador == "openai" and not aj.base_url:
        raise ConfigIAError(f"Falta la URL del endpoint para '{aj.proveedor}' (LLM_BASE_URL)")
    if aj.base_url and urlparse(aj.base_url).scheme not in ("http", "https"):
        raise ConfigIAError(f"URL inválida: {aj.base_url!r} (debe empezar con http:// o https://)")
    if requiere_clave and not aj.api_key:
        raise ConfigIAError(f"Falta la API key del proveedor '{aj.proveedor}'")
    if aj.sintesis_modo not in MODOS_SINTESIS:
        raise ConfigIAError(f"Modo de síntesis inválido: {aj.sintesis_modo!r} (auto, completa o secciones)")
    if not (0 <= aj.timeout_s <= 3600):
        raise ConfigIAError("El timeout debe estar entre 0 y 3600 segundos")


def desde_env() -> Ajustes:
    """Ajustes que define el .env del servidor."""
    cambios = {
        "modelo": settings.llm_model,
        "base_url": settings.llm_base_url,
        "api_key": settings.llm_api_key,
        "temperature": settings.llm_temperature,
        "token_param": settings.llm_token_param,
        "extra_params": settings.llm_extra_params,
        "max_output_techo": settings.llm_max_output_techo,
    }
    if _explicito("llm_json_mode"):
        cambios["json_mode"] = settings.llm_json_mode
    return construir(settings.llm_provider, cambios, origen="env")


def desde_fila(fila: Any) -> Ajustes:
    """Ajustes guardados desde la interfaz (fila de `llm_config`).

    La clave es opcional en la fila: si el administrador no la escribió, se usa la
    que el servidor ya tiene en el .env para ese proveedor (así ops puede dejar las
    claves en el servidor y el administrador solo elige proveedor y modelo)."""
    cambios: dict[str, Any] = {
        "modelo": fila.modelo,
        "base_url": fila.base_url,
        "api_key": fila.api_key,
        "temperature": fila.temperature,
        "token_param": fila.token_param,
        "extra_params": fila.extra_params,
        "context_tokens": fila.context_tokens,
        "timeout_s": fila.timeout_s,
        "sintesis_modo": getattr(fila, "sintesis_modo", None),
    }
    if fila.json_mode is not None:
        cambios["json_mode"] = fila.json_mode
    if not fila.api_key and (fila.proveedor or "").lower() == settings.llm_provider.lower() and settings.llm_api_key:
        cambios["api_key"] = settings.llm_api_key
    return construir(fila.proveedor, cambios, origen="ui")


# ---------------------------------------------------------------------------
#  Lectura con caché (la usan la API y el worker)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cache: tuple[float, Ajustes] | None = None


def _leer_fila_vigente():
    from sqlalchemy import select

    from ..db import SessionLocal
    from ..models import LLMConfig

    with SessionLocal() as db:
        return db.execute(select(LLMConfig).where(LLMConfig.vigente.is_(True))).scalar_one_or_none()


def resolver() -> Ajustes:
    """Ajustes efectivos sin caché: interfaz si hay una válida y permitida; si no, .env."""
    try:
        fila = _leer_fila_vigente()
    except Exception as e:  # noqa: BLE001 — tabla inexistente, BD caída, etc.
        logger.warning("No se pudo leer la configuración de IA desde la BD (%s); se usa el .env", e)
        fila = None
    if fila is not None:
        if (fila.proveedor or "").lower() not in permitidos():
            logger.warning(
                "La configuración de IA de la interfaz usa '%s', que el servidor ya no permite "
                "(LLM_PROVEEDORES_PERMITIDOS); se usa el .env", fila.proveedor,
            )
        else:
            try:
                return desde_fila(fila)
            except ConfigIAError as e:
                logger.error("Configuración de IA de la interfaz inválida (%s); se usa el .env", e)
    return desde_env()


def obtener() -> Ajustes:
    global _cache
    ahora = time.monotonic()
    with _lock:
        if _cache is not None and ahora - _cache[0] < settings.llm_config_cache_s:
            return _cache[1]
    aj = resolver()
    with _lock:
        _cache = (ahora, aj)
    return aj


def invalidar_cache() -> None:
    global _cache
    with _lock:
        _cache = None


# ---------------------------------------------------------------------------
#  Paso de ajustes a una tarea en segundo plano (verificar / descargar)
# ---------------------------------------------------------------------------
def empaquetar(aj: Ajustes) -> str:
    """Serializa los ajustes CIFRADOS (AES-256-GCM) para la cola de Celery.

    La cola y el backend de resultados viven en Redis: la API key nunca debe
    quedar ahí en claro."""
    from ..crypto import encrypt_str

    return encrypt_str(json.dumps(asdict(aj)))


def desempaquetar(paquete: str) -> Ajustes:
    from ..crypto import decrypt_str

    return Ajustes(**json.loads(decrypt_str(paquete)))
