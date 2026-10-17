"""
Abstracción del motor de IA.

Todo el sistema habla con la interfaz `LLMProvider` (4 operaciones) y NUNCA con
un proveedor concreto. Qué modelo responde lo decide la configuración efectiva
(`llm/ajustes.py`): la interfaz de administración o, en su defecto, el .env.

Dos adaptadores cubren cualquier modelo:
  - OpenAICompatProvider: cualquier API compatible con OpenAI (OpenAI, Gemini,
    DeepSeek, Mistral, Groq, Azure/Bedrock/Vertex, OpenRouter, LiteLLM y, en la
    red institucional, Ollama o vLLM).
  - AnthropicProvider: API nativa de Claude.

Agregar un servicio que no sea compatible con ninguno de los dos consiste en
escribir otra subclase de `_ChatJSONProvider` (un método: `_completar`) y
registrarla en `ADAPTADORES`.

El LLM no garantiza JSON estricto, así que cada operación:
  1) pide JSON con prompts explícitos en español (y modo JSON si el servicio lo acepta),
  2) extrae/repara el JSON y lo valida con Pydantic (schemas/llm.py),
  3) reintenta con backoff exponencial; si agota, propaga LLMError.
"""
from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..schemas.llm import (
    BriefingOut,
    ContradiccionesResponse,
    HechosResponse,
    HojaCompletada,
)
from . import ajustes as ajustes_mod
from . import secciones
from .ajustes import Ajustes, ConfigIAError

logger = logging.getLogger(__name__)


# Con una ventana declarada menor que esto, el SITREP se redacta por secciones de entrada.
VENTANA_MIN_COMPLETA = 32768


class LLMError(RuntimeError):
    """Falla irrecuperable del LLM tras agotar reintentos (o configuración inválida)."""


# ---------------------------------------------------------------------------
#  Prompts (español, explícitos, sin preámbulo) — comunes a todos los proveedores
# ---------------------------------------------------------------------------
_EXTRACT_SYS = """Eres un analista de operaciones del Ejército de Chile. Extrae los hechos
operacionales del documento entregado. Responde SOLO con un JSON válido (sin preámbulo,
sin texto adicional, sin markdown) con esta estructura exacta:
{
  "hechos": [
    {
      "evento": "qué ocurrió",
      "ocurrido_en": "cuándo (ISO 8601 si es posible, si no, vacío)",
      "ubicacion": "dónde (área/lugar)",
      "responsable": "quién (unidad/responsable)",
      "impacto": "impacto en personas/medios/servicio",
      "estado": "ABIERTO|EN_CURSO|CERRADO",
      "texto_origen": "cita textual exacta del documento que respalda el hecho"
    }
  ]
}
Reglas: no inventes datos; si un campo no aparece, déjalo como cadena vacía "".
Incluye SIEMPRE "texto_origen" con la cita textual exacta. Usa terminología institucional.
Si no hay hechos claros, devuelve {"hechos": []}."""

_SYNTH_SYS = """Eres un asesor de operaciones del Ejército de Chile. A partir de los HECHOS ya
extraídos (no de los documentos crudos), redacta un briefing operacional institucional.
Responde SOLO con un JSON válido (sin preámbulo, sin markdown) con esta estructura:
{
  "resumen_ejecutivo": ["5 a 10 bullets ejecutivos"],
  "asuntos_criticos": [{"asunto":"...","impacto":"...","responsable":"..."}],
  "proyeccion_24_72h": "proyección de las próximas 24 a 72 horas",
  "situacion": {"resumen":"panorama operacional general (situación) en 2-4 frases","aspectos":["aspecto relevante de la situación","..."]},
  "personal": {
    "parte_fuerza_institucional": {"OF":"-.-","SOF":"-.-","ECP":"-.-","SLTP":"-.-","ESCMIL":"-.-","ESCSOF":"-.-","ESCSERV":"-.-","personal_civil":"-.-","SLC":"-.-","total":"-.-"},
    "slc": {"clase_2006":"-.-","clase_2007":"-.-","total":"-.-"},
    "macrozonas": [{"zona":"...","fuerza":"-.-","forman":"-.-","faltan":"-.-"}],
    "catastrofe": {"fuerza":"-.-","forman":"-.-","faltan":"-.-"},
    "unidades_emergencia": {"ufec":"-.-","brife":"-.-","parme":"-.-"}
  },
  "inteligencia": {
    "incidentes_institucionales": [{"tipo":"...","descripcion":"..."}],
    "incidentes_mootw": [{"tipo":"...","unidad":"...","descripcion":"..."}],
    "sistema_alerta": [{"alerta":"...","area":"...","unidad_asociada":"...","apreciacion":"..."}],
    "analisis_meteo": "...",
    "proyeccion_meteo_48h": "..."
  },
  "operaciones": {
    "ops_catastrofe": [{"cantidad":"-.-","tipo":"...","unidad_origen":"...","zona_empleo":"...","inicio_empleo":"..."}],
    "relevos_norte": [{"n":"...","fecha":"...","jaf":"...","unidades":"...","periodo":"..."}],
    "relevos_sur": [{"n":"...","fecha":"...","ft":"...","unidades":"...","periodo":"..."}],
    "ops_antartica": [{"bae":"...","dotacion_estival":"-.-","cpccgu":"..."}],
    "ops_extranjero": [{"operacion":"...","efectivos":"-.-","ubicacion":"...","repliegue":"..."}],
    "guardian_soberano": [{"jaf":"...","fuerza":"-.-","planif":"-.-","ejecut":"-.-"}],
    "unidades_terreno_kpi": {"unidades_en_terreno":"-.-","fuerza_en_terreno":"-.-","lugares_activos":"-.-","actividad_principal":"..."},
    "traslados_uac": [{"uac":"...","unidades":"-.-"}],
    "unidades_terreno": [{"actividad":"...","comando_matriz":"...","ur":"...","fechas":"...","ubicacion":"...","fuerza":"-.-"}],
    "despliegue_mapa": {"mzn":"-.-","mzs":"-.-","antartica":"-.-"}
  },
  "logistica": {
    "resumen": {"total":"-.-","nop":"-.-"},
    "operacionalidad": [{"unidad":"...","total":"-.-","nop":"-.-","campana":"-.-","combate":"-.-","administrativos":"-.-","eq_ingenieros":"-.-"}]
  },
  "trazabilidad": {"resumen_ejecutivo[0]": ["id-de-hecho", "..."]}
}
Reglas: el briefing DEBE incluir un resumen por sección (RF-004): "situacion" (panorama
general), "personal", "logistica", incidentes (en "inteligencia") y meteorología (en
"inteligencia.analisis_meteo"); completa "situacion" con lo que aporten los hechos/contexto.
Cada bullet/casilla con dato debe poder rastrearse a los hechos que lo originan;
incluye sus ids en "trazabilidad" usando como clave la ruta del bullet (p.ej. "resumen_ejecutivo[0]").
Donde no haya dato, usa "-.-". No inventes cifras. Mantén entre 5 y 10 bullets en resumen_ejecutivo.
Si en "parametros.contexto_fuentes" aparecen cifras o datos (personal OF/SOF/ECP/total, fuerzas por
macrozona, operacionalidad/NOP con sus categorías campaña/combate/administrativos/eq_ingenieros,
unidades de emergencia UFEC/BRIFE/PARME, guardián soberano con trabajos de tierra planificados/
ejecutados, traslados por UAC, despliegue por macrozona MZN/MZS/Antártica, relevos con su periodo,
meteorología, incidentes), ÚSALOS para completar las casillas institucionales correspondientes;
si no aparecen en el contexto ni en los hechos, deja "-.-". En "traslados_uac" usa el nombre corto
de la UAC tal como aparezca en la fuente (p.ej. "I DE", "COPE", "CAF")."""

_CONTRA_SYS = """Eres un analista de operaciones del Ejército de Chile. Te entrego una lista de
HECHOS (cada uno con su id). Identifica solo CONTRADICCIONES REALES: dos o más hechos que
describen el MISMO evento/situación pero con datos INCOMPATIBLES entre sí (cifras distintas,
estados opuestos como ABIERTO vs CERRADO, fechas o ubicaciones que no calzan, afirmaciones
que se excluyen).
REGLAS IMPORTANTES:
- NO marques como contradicción los hechos meramente repetidos o idénticos (eso es duplicado,
  no contradicción). Si el contenido coincide, NO es contradicción.
- En "descripcion" explica el conflicto en lenguaje natural claro (qué dato choca con qué),
  SIN escribir ids ni UUIDs en el texto. Los ids van solo en "hechos_involucrados".
Responde SOLO con JSON válido:
{"contradicciones":[{"descripcion":"...","hechos_involucrados":["id1","id2"],"severidad":1}]}
severidad: 1 baja, 2 media, 3 alta. Si no hay contradicciones reales, devuelve {"contradicciones": []}."""

_HOJA_SYS = """Eres un asesor de operaciones del Ejército de Chile. El mando pidió una HOJA ADICIONAL
para el reporte institucional. Recibes: la hoja ("titulo", "seccion", "instrucciones" del mando y
"bloques" con el formato que eligió el usuario), los HECHOS extraídos (cada uno con su id) y el
"contexto_fuentes" (texto de los documentos). Completa la hoja SOLO con datos presentes en los
hechos/contexto. Si "documentos_adjuntos" no está vacío, el "contexto_fuentes" contiene el texto de esos
documentos (cada uno encabezado por [nombre]) y son la fuente PRINCIPAL: extrae de ellos toda la
información relevante (cifras, tablas, listados, fechas, unidades) y vuélcala en los bloques; una tabla
del documento debe quedar como bloque "tabla" con sus mismas columnas y filas. Responde SOLO con JSON válido (sin preámbulo ni markdown):
{"titulo": "...", "bloques": [ ... ], "trazabilidad": {"b0": ["id-de-hecho"]}}
"titulo": solo si la hoja NO traía título (propón uno breve, en mayúsculas); si ya traía, devuélvelo vacío.
Cada bloque tiene "tipo" y sus campos:
- texto:   {"tipo":"texto","titulo":"...","texto":"..."}
- vinetas: {"tipo":"vinetas","titulo":"...","items":["..."]}
- tabla:   {"tipo":"tabla","titulo":"...","columnas":["..."],"filas":[["...","..."]]}
- kpis:    {"tipo":"kpis","titulo":"...","items":[{"etiqueta":"...","valor":"..."}]}
- grafico: {"tipo":"grafico","titulo":"...","estilo":"barras|barras_h|dona","categorias":["..."],"valores":[1,2]}
- imagen:  NO la completes; devuélvela tal cual venía.
Reglas: si "bloques" trae estructura, RESPÉTALA (mismos tipos, mismo orden, mismas columnas y títulos) y
solo rellena el contenido; si viene vacío, propón el formato más adecuado a las instrucciones (máx. 4 bloques).
NO inventes cifras ni datos: si no hay información, deja el campo vacío ("" o lista vacía). En "valores"
usa números. En "trazabilidad" la clave es "b<índice del bloque>" y el valor los ids de los hechos que lo
respaldan (solo ids que existan en los hechos entregados)."""



class LLMProvider(ABC):
    """Contrato que cumple cualquier proveedor (nube o modelo local)."""

    nombre: str = "?"
    modelo: str = "?"

    @abstractmethod
    def extraer_hechos(self, texto: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def sintetizar_briefing(self, hechos: list[dict[str, Any]], parametros: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def detectar_contradicciones(self, hechos: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def completar_hoja(self, hechos: list[dict[str, Any]], contexto: str, hoja: dict[str, Any]) -> dict[str, Any]: ...

    def info(self) -> dict[str, str]:
        """Proveedor y modelo, para auditoría y trazabilidad (sin secretos)."""
        return {"proveedor": self.nombre, "modelo": self.modelo, "firma": f"{self.nombre}/{self.modelo}"}


# ---------------------------------------------------------------------------
#  Utilidades JSON
# ---------------------------------------------------------------------------
_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


def _strip_fences(s: str) -> str:
    """Quita ```json ... ``` si el modelo lo agrega pese a las instrucciones."""
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[: s.rfind("```")]
    return s.strip()


def _extraer_json(texto: str) -> str:
    """Aísla el objeto JSON de la respuesta.

    Sin modo JSON (o con modelos locales que "piensan" en voz alta) la respuesta
    puede traer razonamiento <think>…</think>, bloques markdown o una frase antes
    del JSON. Se toma desde la primera '{' hasta la última '}'.
    """
    t = _strip_fences(_THINK_RE.sub("", texto or ""))
    if t.startswith("{"):
        return t
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        return t[i: j + 1]
    if i != -1:
        return t[i:]  # JSON cortado: lo resuelve la lógica de truncación
    return t


def _try_repair_json(raw: str) -> dict[str, Any] | None:
    """Intenta reparar JSON mal formado (comas, comillas) que NO se truncó."""
    try:
        from json_repair import repair_json  # import perezoso

        fixed = repair_json(raw)
        if not fixed:
            return None
        data = json.loads(fixed)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


@dataclass
class Respuesta:
    texto: str
    truncado: bool
    tokens_entrada: int | None = None
    tokens_salida: int | None = None


# ---------------------------------------------------------------------------
#  Base común: prompts, JSON, reintentos y registro por llamada
# ---------------------------------------------------------------------------
class _ChatJSONProvider(LLMProvider):
    max_retries: int = 3
    max_output_tokens: int = 32768
    # Techo al que se puede escalar la salida si se trunca (depende del modelo).
    max_output_techo: int = 32768

    @abstractmethod
    def _completar(self, system: str, user: str, max_tokens: int) -> Respuesta:
        """Una llamada al servicio. Única pieza que cambia entre adaptadores."""

    # Errores donde reintentar no sirve (clave inválida, sin permiso, modelo inexistente,
    # petición rechazada). Mismos nombres en los SDK de OpenAI y de Anthropic.
    _ERRORES_DEFINITIVOS = ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "BadRequestError")

    def _error_definitivo(self, e: Exception) -> bool:
        return type(e).__name__ in self._ERRORES_DEFINITIVOS

    def _log_uso(self, operacion: str, intento: int, latencia: float, resultado: str,
                 r: Respuesta | None, falla: Exception | None) -> None:
        """Una línea por llamada, SOLO metadatos: nunca el contenido de prompts ni respuestas
        (los documentos pueden ser clasificados). De una excepción se registra solo su tipo."""
        logger.info(
            "llm_call provider=%s model=%s op=%s intento=%d/%d latencia_s=%.2f "
            "tokens_in=%s tokens_out=%s resultado=%s%s",
            self.nombre, self.modelo, operacion, intento, self.max_retries, latencia,
            r.tokens_entrada if r else None, r.tokens_salida if r else None, resultado,
            f" error={type(falla).__name__}" if falla else "",
        )

    def _chat_json(self, system: str, user: str, *, operacion: str = "?") -> dict[str, Any]:
        """Pide JSON al modelo y reintenta con backoff.

        Una respuesta cortada por el tope de tokens NUNCA se acepta "reparada": json_repair
        cerraría las llaves y Pydantic rellenaría con vacíos las secciones que faltan
        (un briefing incompleto que parece válido). En ese caso se reintenta con más
        tokens de salida y, si ya no se puede, se falla con LLMError.
        json_repair solo se usa para JSON mal formado que NO se truncó.
        """
        last_err: Exception | None = None
        max_tokens = self.max_output_tokens
        for intento in range(1, self.max_retries + 1):
            t0 = time.perf_counter()
            r: Respuesta | None = None
            resultado, falla, latencia = "error", None, None
            try:
                r = self._completar(system, user, max_tokens)
                latencia = time.perf_counter() - t0
                raw = _extraer_json(r.texto)
                try:
                    data = json.loads(raw)  # JSON completo y válido (aunque roce el tope)
                    if not isinstance(data, dict):
                        raise json.JSONDecodeError("se esperaba un objeto JSON", raw, 0)
                except json.JSONDecodeError as e:
                    if r.truncado:
                        resultado = "truncado"
                        logger.warning(
                            "Salida LLM truncada (provider=%s model=%s max_tokens=%s tokens_out=%s)",
                            self.nombre, self.modelo, max_tokens, r.tokens_salida,
                        )
                        if max_tokens < self.max_output_techo:
                            max_tokens = min(max_tokens * 2, self.max_output_techo)
                            last_err = LLMError("salida truncada por el tope de tokens")
                            continue  # reintenta de inmediato con más tokens de salida
                        raise LLMError(
                            "La respuesta del LLM superó el tope de tokens de salida "
                            f"({max_tokens}) y quedó incompleta; no se acepta un resultado a medias. "
                            "Sube LLM_MAX_OUTPUT_TOKENS o reduce el alcance (menos fuentes)."
                        ) from e
                    reparado = _try_repair_json(raw)
                    if reparado is None:
                        resultado = "json_invalido"
                        raise
                    resultado = "ok_reparado"
                    return reparado
                resultado = "ok"
                return data
            except LLMError as e:
                falla = e
                raise  # error definitivo (truncación irreparable, rechazo): no reintentar
            except Exception as e:  # red, timeout, JSON inválido transitorio, etc.
                falla = last_err = e
                if self._error_definitivo(e):
                    raise LLMError(f"Error no recuperable de {self.nombre}/{self.modelo}: {e}") from e
                if intento < self.max_retries:
                    time.sleep(2 ** (intento - 1))  # 1s, 2s, 4s...
            finally:
                self._log_uso(operacion, intento,
                              time.perf_counter() - t0 if latencia is None else latencia,
                              resultado, r, falla)
        raise LLMError(f"LLM ({self.nombre}/{self.modelo}) falló tras {self.max_retries} intentos: {last_err}")

    # ---- Las cuatro operaciones del sistema ----
    def extraer_hechos(self, texto: str) -> list[dict[str, Any]]:
        data = self._chat_json(_EXTRACT_SYS, texto, operacion="extraccion")
        try:
            parsed = HechosResponse.model_validate(data)
        except ValidationError as e:
            raise LLMError(f"Extracción con formato inválido: {e}")
        return [h.model_dump() for h in parsed.hechos]

    def sintetizar_briefing(self, hechos: list[dict[str, Any]], parametros: dict[str, Any]) -> dict[str, Any]:
        """Redacta el SITREP de una vez o por secciones según `sintesis_modo`.

        auto: si la ventana declarada es chica (< 32k) va directo por secciones; si no,
        intenta de una vez y, si el modelo no lo logra (JSON cortado o inválido), lo
        rehace por secciones. Así un modelo chico también entrega el SITREP."""
        aj = getattr(self, "aj", None)
        modo = getattr(aj, "sintesis_modo", "completa") or "completa"
        if modo == "auto" and aj is not None and aj.context_tokens and aj.context_tokens < VENTANA_MIN_COMPLETA:
            modo = "secciones"
        if modo == "secciones":
            return self.sintetizar_por_secciones(hechos, parametros)
        try:
            return self._sintetizar_completa(hechos, parametros)
        except LLMError as e:
            if modo != "auto":
                raise
            logger.warning(
                "Síntesis completa falló con %s/%s (%s); se rehace por secciones", self.nombre, self.modelo, e
            )
            return self.sintetizar_por_secciones(hechos, parametros, respaldo=True)

    def _sintetizar_completa(self, hechos: list[dict[str, Any]], parametros: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"hechos": hechos, "parametros": parametros}, ensure_ascii=False)
        data = self._chat_json(_SYNTH_SYS, payload, operacion="sintesis")
        try:
            out = BriefingOut.model_validate(data).model_dump()
        except ValidationError as e:
            raise LLMError(f"Síntesis con formato inválido: {e}")
        out["generacion"] = {"modo": "completa", "avisos": []}
        return out

    def sintetizar_por_secciones(
        self,
        hechos: list[dict[str, Any]],
        parametros: dict[str, Any],
        *,
        respaldo: bool = False,
        secciones_a_usar: tuple | None = None,
    ) -> dict[str, Any]:
        try:
            data, avisos = secciones.sintetizar(
                self._chat_json, hechos, parametros,
                secciones=secciones_a_usar or secciones.SECCIONES,
            )
        except LLMError:
            raise
        except Exception as e:  # sección obligatoria incompleta
            raise LLMError(f"Síntesis por secciones falló en el resumen ejecutivo: {e}") from e
        try:
            out = BriefingOut.model_validate(data).model_dump()
        except ValidationError as e:
            raise LLMError(f"Síntesis por secciones con formato inválido: {e}")
        out["generacion"] = {"modo": "secciones (respaldo)" if respaldo else "secciones", "avisos": avisos}
        return out

    def detectar_contradicciones(self, hechos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(hechos) < 2:
            return []
        payload = json.dumps({"hechos": hechos}, ensure_ascii=False)
        data = self._chat_json(_CONTRA_SYS, payload, operacion="contradicciones")
        try:
            return [c.model_dump() for c in ContradiccionesResponse.model_validate(data).contradicciones]
        except ValidationError:
            return []  # la detección de contradicciones es best-effort

    def completar_hoja(self, hechos: list[dict[str, Any]], contexto: str, hoja: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(
            {
                "hoja": {
                    "id": hoja.get("id", ""),
                    "titulo": hoja.get("titulo", ""),
                    "seccion": hoja.get("seccion", ""),
                    "instrucciones": hoja.get("instrucciones_ia", ""),
                    "documentos_adjuntos": [d.get("nombre", "") for d in hoja.get("documentos", [])],
                    "bloques": hoja.get("bloques", []),
                },
                "hechos": hechos,
                "contexto_fuentes": contexto,
            },
            ensure_ascii=False,
        )
        data = self._chat_json(_HOJA_SYS, payload, operacion="hoja")
        try:
            return HojaCompletada.model_validate(data).model_dump()
        except ValidationError as e:
            raise LLMError(f"Hoja con formato inválido: {e}")


# ---------------------------------------------------------------------------
#  Adaptadores
# ---------------------------------------------------------------------------
class OpenAICompatProvider(_ChatJSONProvider):
    """Cualquier servicio con API estilo OpenAI (chat.completions).

    Lo que varía entre servicios se toma de los ajustes, no del código:
      - json_mode:    response_format=json_object (algunos servicios no lo aceptan),
      - temperature:  None = no se envía (modelos de razonamiento la rechazan),
      - token_param:  max_tokens | max_completion_tokens,
      - extra_params: se agregan al body tal cual (p.ej. reasoning_effort de Gemini,
                      thinking de DeepSeek); van en `extra_body` para aceptar campos
                      que el SDK de OpenAI no conoce.
    """

    def __init__(self, aj: Ajustes, client: Any = None) -> None:
        self.aj = aj
        self.nombre = aj.proveedor
        self.modelo = aj.modelo
        self.max_retries = aj.max_retries
        self.max_output_tokens = aj.max_output_tokens
        self.max_output_techo = aj.max_output_techo
        if client is None:
            from openai import OpenAI  # import perezoso

            client = OpenAI(
                base_url=aj.base_url,
                api_key=aj.api_key or "sin-clave",  # Ollama/vLLM no la exigen; el SDK sí
                timeout=aj.timeout_s,
                max_retries=0,  # los reintentos los maneja _chat_json
            )
        self.client = client

    def _kwargs(self, system: str, user: str, max_tokens: int) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": self.aj.modelo,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            self.aj.token_param: max_tokens,
        }
        if self.aj.json_mode:
            kw["response_format"] = {"type": "json_object"}
        if self.aj.temperature is not None:
            kw["temperature"] = self.aj.temperature
        if self.aj.extra_params:
            kw["extra_body"] = dict(self.aj.extra_params)
        return kw

    def _completar(self, system: str, user: str, max_tokens: int) -> Respuesta:
        resp = self.client.chat.completions.create(**self._kwargs(system, user, max_tokens))
        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        return Respuesta(
            texto=choice.message.content or "",
            truncado=choice.finish_reason == "length",
            tokens_entrada=getattr(usage, "prompt_tokens", None),
            tokens_salida=getattr(usage, "completion_tokens", None),
        )


class LocalLLMProvider(OpenAICompatProvider):
    """Modelo de pesos abiertos dentro de la red institucional (Ollama / vLLM).

    Ambos exponen la API compatible con OpenAI, así que es el mismo adaptador;
    la clase existe para que el despliegue on-premise sea explícito en los logs.
    """


class AnthropicProvider(_ChatJSONProvider):
    """Claude por su API nativa (Messages).

    Se usa la API nativa porque la capa compatible con OpenAI de Anthropic ignora
    response_format. El JSON se pide por prompt y se aísla con `_extraer_json`.
    """

    def __init__(self, aj: Ajustes, client: Any = None) -> None:
        self.aj = aj
        self.nombre = aj.proveedor
        self.modelo = aj.modelo
        self.max_retries = aj.max_retries
        self.max_output_tokens = aj.max_output_tokens
        self.max_output_techo = aj.max_output_techo
        if client is None:
            try:
                from anthropic import Anthropic  # import perezoso
            except ImportError as e:  # pragma: no cover - depende de la imagen
                raise LLMError(
                    "Falta la librería 'anthropic' (está en requirements.txt): reconstruir las "
                    "imágenes api y worker con `docker compose build api worker`."
                ) from e
            client = Anthropic(
                api_key=aj.api_key,
                base_url=aj.base_url or None,
                timeout=aj.timeout_s,
                max_retries=0,
            )
        self.client = client

    def _kwargs(self, system: str, user: str, max_tokens: int) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": self.aj.modelo,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
        }
        if self.aj.temperature is not None:
            kw["temperature"] = self.aj.temperature
        if self.aj.extra_params:
            kw["extra_body"] = dict(self.aj.extra_params)
        return kw

    def _completar(self, system: str, user: str, max_tokens: int) -> Respuesta:
        # Streaming: con max_tokens alto el SDK lo exige para evitar cortes HTTP.
        with self.client.messages.stream(**self._kwargs(system, user, max_tokens)) as stream:
            resp = stream.get_final_message()
        if resp.stop_reason == "refusal":
            raise LLMError("Claude rechazó la solicitud (stop_reason=refusal); no se reintenta.")
        texto = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        usage = getattr(resp, "usage", None)
        return Respuesta(
            texto=texto,
            truncado=resp.stop_reason == "max_tokens",
            tokens_entrada=getattr(usage, "input_tokens", None),
            tokens_salida=getattr(usage, "output_tokens", None),
        )


# Registro adaptador → clase. `local` usa su propia clase (mismo protocolo).
ADAPTADORES: dict[str, type[_ChatJSONProvider]] = {
    "openai": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
}


def crear_proveedor(aj: Ajustes, client: Any = None) -> LLMProvider:
    """Instancia el adaptador que corresponde a los ajustes."""
    if aj.proveedor == "local":
        return LocalLLMProvider(aj, client)
    clase = ADAPTADORES.get(aj.adaptador)
    if clase is None:
        raise LLMError(f"Adaptador desconocido: {aj.adaptador!r}. Disponibles: {', '.join(ADAPTADORES)}")
    return clase(aj, client)


def get_llm_provider() -> LLMProvider:
    """Proveedor según la configuración efectiva (interfaz o .env).

    Un proveedor desconocido o mal configurado DETIENE la operación con un error
    claro; nunca se cae en silencio a otro proveedor (los documentos podrían
    terminar en un servicio no autorizado)."""
    try:
        return crear_proveedor(ajustes_mod.obtener())
    except ConfigIAError as e:
        raise LLMError(f"Configuración de IA inválida: {e}") from e


def probar_conexion(aj: Ajustes) -> dict[str, Any]:
    """Llamada mínima para validar URL, clave, modelo y modo JSON antes de guardar."""
    t0 = time.perf_counter()
    try:
        p = crear_proveedor(aj)
        p.max_retries = 1  # type: ignore[attr-defined]
        p.max_output_tokens = min(p.max_output_tokens, 2048)  # type: ignore[attr-defined]
        data = p._chat_json(  # type: ignore[attr-defined]
            "Eres un verificador de conexión. Responde SOLO con un objeto JSON válido, sin texto adicional.",
            'Devuelve exactamente este JSON: {"ok": true, "idioma": "es"}',
            operacion="prueba",
        )
        return {
            "ok": bool(data.get("ok", True)),
            "latencia_ms": int((time.perf_counter() - t0) * 1000),
            "respuesta": data,
            "proveedor": aj.proveedor,
            "modelo": aj.modelo,
        }
    except Exception as e:  # noqa: BLE001 — se informa a la interfaz, sin la clave
        return {
            "ok": False,
            "latencia_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(e)[:500],
            "proveedor": aj.proveedor,
            "modelo": aj.modelo,
        }


# ---------------------------------------------------------------------------
#  Catálogo de modelos que ofrece un servicio
# ---------------------------------------------------------------------------
def listar_modelos(aj: Ajustes) -> list[str]:
    """Modelos que el servicio dice tener (GET /models), para elegirlos de una lista.

    Funciona con OpenAI, Gemini, Mistral, Groq, DeepSeek, OpenRouter, Azure v1, vLLM,
    Ollama (los modelos ya descargados), LiteLLM (los declarados en su config) y la
    API de Anthropic. Si el servicio no publica su catálogo se lanza LLMError y la
    interfaz deja escribir el nombre a mano."""
    try:
        if aj.adaptador == "anthropic":
            from anthropic import Anthropic

            cli = Anthropic(api_key=aj.api_key, base_url=aj.base_url or None, timeout=30, max_retries=0)
            ids = [m.id for m in cli.models.list(limit=1000)]
        else:
            from openai import OpenAI

            cli = OpenAI(base_url=aj.base_url, api_key=aj.api_key or "sin-clave", timeout=30, max_retries=0)
            ids = [m.id for m in cli.models.list()]
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"El servicio no entregó su lista de modelos: {str(e)[:300]}") from e
    # Gemini antepone "models/" en su endpoint compatible; la API espera el id sin prefijo.
    limpios = {i.removeprefix("models/") for i in ids if i}
    return sorted(limpios, key=str.lower)


# ---------------------------------------------------------------------------
#  Verificación de un modelo con un caso real (sintético)
# ---------------------------------------------------------------------------
# Documento FICTICIO (no clasificado) con datos conocidos para comprobar que el
# modelo extrae, redacta y respeta cifras. Las cifras esperadas están abajo.
MUESTRA_PARTE = """PARTE OPERACIONAL DIARIO N° 999 — DOCUMENTO DE PRUEBA (DATOS FICTICIOS)
Fecha: 14 de octubre de 2026, 08:00 horas. Unidad informante: Regimiento de Prueba N° 1.
1. A las 03:40 horas un incendio forestal afectó el sector Cerro Alto, comuna de Ejemplo.
   La Compañía de Ingenieros apoyó con 2 camiones aljibe; el incendio sigue EN CURSO y no hay heridos.
2. A las 06:15 horas se cortó el puente Río Claro por crecida; la ruta queda interrumpida y se
   habilitó un desvío por camino interior. Responsable: Batallón Logístico. Estado: ABIERTO.
3. Se completó la evacuación preventiva de 35 familias del sector Las Vegas a las 07:30 horas.
   Estado: CERRADO.
PERSONAL: Oficiales (OF) 120, Suboficiales (SOF) 340, Soldados (SLC) 780. Total de efectivos: 1240.
METEOROLOGÍA: lluvias intensas próximas 48 horas, viento norte de 60 km/h."""

_TOTAL_ESPERADO = "1240"
_PALABRAS_ESPERADAS = ("incendio", "puente", "evacu")


def _paso(nombre: str, ok: bool | None, t0: float, detalle: str, **extra: Any) -> dict[str, Any]:
    estado = "ok" if ok else ("advertencia" if ok is None else "falla")
    return {"paso": nombre, "estado": estado, "latencia_ms": int((time.perf_counter() - t0) * 1000),
            "detalle": detalle, **extra}


def verificar_modelo(aj: Ajustes, al_avanzar: Any = None) -> dict[str, Any]:
    """Prueba el modelo con un parte ficticio: conexión, extracción, redacción y cifras.

    Veredicto:
      COMPATIBLE                    los 4 pasos bien,
      COMPATIBLE_CON_OBSERVACIONES  funciona, pero no respetó una cifra (revisar a mano),
      NO_COMPATIBLE                 falló la conexión, la extracción o el resumen.
    No reemplaza la certificación del Robot QA (campaña completa)."""
    pasos: list[dict[str, Any]] = []
    total = 4

    def avance(i: int, texto: str) -> None:
        if al_avanzar:
            al_avanzar({"paso_actual": i, "total": total, "descripcion": texto, "pasos": pasos})

    def cerrar(veredicto: str, resumen: str) -> dict[str, Any]:
        return {"veredicto": veredicto, "resumen": resumen, "pasos": pasos,
                "proveedor": aj.proveedor, "modelo": aj.modelo, "firma": aj.firma(),
                "modo_sintesis_recomendado": (
                    "secciones" if (aj.context_tokens and aj.context_tokens < VENTANA_MIN_COMPLETA)
                    else aj.sintesis_modo)}

    # 1) Conexión y JSON
    avance(1, "Conexión y respuesta en JSON")
    t0 = time.perf_counter()
    r = probar_conexion(aj)
    pasos.append(_paso("Conexión y respuesta en JSON", r["ok"], t0,
                       "El servicio respondió JSON válido." if r["ok"] else r.get("error", "sin respuesta")))
    if not r["ok"]:
        return cerrar("NO_COMPATIBLE", "No se pudo conectar o el modelo no responde en JSON.")

    p = crear_proveedor(aj)
    p.max_retries = 2  # type: ignore[attr-defined]

    # 2) Extracción de hechos
    avance(2, "Extracción de hechos de un parte de prueba")
    t0 = time.perf_counter()
    try:
        hechos = p.extraer_hechos(MUESTRA_PARTE)
        texto = " ".join((h.get("evento", "") + " " + h.get("texto_origen", "")).lower() for h in hechos)
        hallados = [w for w in _PALABRAS_ESPERADAS if w in texto]
        con_cita = sum(1 for h in hechos if h.get("texto_origen"))
        ok = len(hechos) >= 2 and len(hallados) >= 2
        pasos.append(_paso(
            "Extracción de hechos", ok, t0,
            f"{len(hechos)} hechos extraídos ({con_cita} con cita textual); "
            f"reconoció {len(hallados)} de 3 eventos del parte.",
            hechos=len(hechos)))
    except Exception as e:  # noqa: BLE001
        hechos, ok = [], False
        pasos.append(_paso("Extracción de hechos", False, t0, str(e)[:300]))
    if not ok:
        return cerrar("NO_COMPATIBLE", "El modelo no extrae bien los hechos de un parte operacional.")

    hechos_payload = [{**h, "id": f"h{i}"} for i, h in enumerate(hechos)]
    params = {"contexto_fuentes": f"[parte_prueba.txt]\n{MUESTRA_PARTE}"}
    por_clave = {s.clave: s for s in secciones.SECCIONES}

    # 3) Resumen ejecutivo (la sección obligatoria del SITREP)
    avance(3, "Redacción del resumen ejecutivo")
    t0 = time.perf_counter()
    try:
        out = p.sintetizar_por_secciones(hechos_payload, params, secciones_a_usar=(por_clave["ejecutivo"],))  # type: ignore[attr-defined]
        bullets = [b for b in out.get("resumen_ejecutivo", []) if str(b).strip()]
        ok = len(bullets) >= 3
        pasos.append(_paso("Resumen ejecutivo", ok, t0, f"{len(bullets)} bullets redactados.",
                           ejemplo=bullets[0][:200] if bullets else ""))
    except Exception as e:  # noqa: BLE001
        ok = False
        pasos.append(_paso("Resumen ejecutivo", False, t0, str(e)[:300]))
    if not ok:
        return cerrar("NO_COMPATIBLE", "El modelo no logra redactar el resumen ejecutivo del SITREP.")

    # 4) Una sección con cifras: ¿respeta los números del documento?
    avance(4, "Sección PERSONAL: respeto de cifras")
    t0 = time.perf_counter()
    try:
        out = p.sintetizar_por_secciones(hechos_payload, params, secciones_a_usar=(por_clave["personal"],))  # type: ignore[attr-defined]
        total_pf = str(((out.get("personal") or {}).get("parte_fuerza_institucional") or {}).get("total", ""))
        digitos = "".join(ch for ch in total_pf if ch.isdigit())
        ok4 = digitos == _TOTAL_ESPERADO
        pasos.append(_paso(
            "Cifras de la sección PERSONAL", True if ok4 else None, t0,
            "Copió el total de efectivos correcto (1240)." if ok4
            else f"Total de efectivos esperado 1240, el modelo entregó {total_pf or 'vacío'!r}."))
    except Exception as e:  # noqa: BLE001
        ok4 = False
        pasos.append(_paso("Cifras de la sección PERSONAL", None, t0, str(e)[:300]))

    if ok4:
        return cerrar("COMPATIBLE", "El modelo puede generar el SITREP. Certificar con el Robot QA antes de producción.")
    return cerrar("COMPATIBLE_CON_OBSERVACIONES",
                  "El modelo genera el SITREP, pero no respetó una cifra: revisar las tablas antes de aprobar.")
