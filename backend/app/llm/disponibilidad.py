"""
Disponibilidad de modelos: ¿el modelo existe y esta clave puede usarlo HOY?

La lista que publica un servicio (GET /models) no basta: trae modelos de imagen,
audio o embeddings que no sirven para redactar, modelos privados o de pago que la
clave no puede usar, y los proveedores retiran modelos sin aviso (p.ej. Groq
apagó llama-3.3-70b-versatile). Aquí se hace una llamada mínima (un "hola" de
pocos tokens, sin documentos) por modelo y se clasifica la respuesta en un
estado que la interfaz muestra con su causa.

Estados:
  disponible    responde
  sin_cuota     existe, pero el plan no tiene cuota ahora (429): reintentar más tarde
  sin_acceso    la clave no puede usarlo (403, o 429 con límite 0 del plan gratuito)
  clave         la clave no es válida (401)
  no_existe     el proveedor no lo tiene: retirado o nombre mal escrito (404)
  incompatible  existe pero no acepta conversaciones de texto (imagen, audio…)
  no_descargado (Ollama) no está descargado en el servidor local
  error         no respondió (red, tiempo agotado u otro)
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .ajustes import Ajustes

# Modelos que los servicios listan pero que no redactan texto (imagen, audio, video,
# embeddings, moderación, búsqueda profunda…). Se ocultan de la lista para elegir.
_NO_CHAT = re.compile(
    r"(embed|embedding|tts|whisper|transcri|audio|speech|realtime|live|image|imagen|dall-e|"
    r"gpt-image|veo|lyria|nano-banana|vision-preview|moderation|guard|safeguard|"
    r"orpheus|playai|distil-whisper|deep-research|computer-use|aqa|rerank|ocr|"
    r"babbage|davinci-00|text-similarity|search-)",
    re.IGNORECASE,
)

ESTADOS = ("disponible", "sin_cuota", "sin_acceso", "clave", "no_existe", "incompatible",
           "no_descargado", "error")

_MENSAJES = {
    "disponible": "Disponible: el modelo respondió con esta clave.",
    "sin_cuota": "Existe, pero su plan no tiene cuota disponible ahora (límite por minuto o por día). "
                 "Vuelva a intentar más tarde o use un plan pagado.",
    "sin_acceso": "Su clave no tiene acceso a este modelo (privado, de pago o no incluido en su plan).",
    "clave": "La clave API no es válida para este servicio.",
    "no_existe": "El proveedor no tiene este modelo: fue retirado o el nombre está mal escrito.",
    "incompatible": "El modelo existe pero no acepta conversaciones de texto (p.ej. es de imagen, "
                    "audio o embeddings).",
    "no_descargado": "No está descargado en el servidor local. Use “Descargar”.",
    "error": "El servicio no respondió a tiempo o hubo un error de red.",
}


def es_modelo_de_chat(nombre: str) -> bool:
    return not _NO_CHAT.search(nombre or "")


def filtrar_chat(ids: list[str]) -> tuple[list[str], int]:
    """(modelos que sirven para redactar, cantidad ocultada)."""
    chat = [m for m in ids if es_modelo_de_chat(m)]
    return chat, len(ids) - len(chat)


def _texto_error(e: Exception) -> str:
    cuerpo = getattr(e, "body", None)
    return f"{e} {cuerpo or ''}".lower()


def clasificar_error(e: Exception) -> str:
    """Traduce el error de una llamada mínima a un estado de disponibilidad."""
    codigo = getattr(e, "status_code", None)
    nombre = type(e).__name__
    texto = _texto_error(e)
    if codigo == 404 or nombre == "NotFoundError" or "model_not_found" in texto or "decommission" in texto:
        return "no_existe"
    if codigo == 401 or nombre == "AuthenticationError":
        return "clave"
    if codigo == 403 or nombre == "PermissionDeniedError":
        return "sin_acceso"
    if codigo == 429 or nombre == "RateLimitError":
        # Gemini responde 429 con "limit: 0" cuando el plan gratuito no incluye el modelo.
        if re.search(r"limit:\s*0\b", texto) or "limit\": 0" in texto:
            return "sin_acceso"
        return "sin_cuota"
    if codigo in (400, 422) or nombre in ("BadRequestError", "UnprocessableEntityError"):
        if re.search(r"model.{0,40}(not found|does not exist|not exist|unknown|invalid model|no longer)", texto):
            return "no_existe"
        if re.search(r"(max_tokens|max_completion_tokens|max_output|token)", texto):
            # Existe y responde; solo objetó el tope de esta prueba (el sistema se ajusta solo).
            return "disponible"
        return "incompatible"
    if codigo == 413:
        return "disponible"
    return "error"


def _ping(aj: Ajustes, modelo: str) -> None:
    """Llamada mínima: un mensaje corto y pocos tokens de salida (sin documentos)."""
    if aj.adaptador == "anthropic":
        from anthropic import Anthropic

        cli = Anthropic(api_key=aj.api_key, base_url=aj.base_url or None, timeout=25, max_retries=0)
        cli.messages.create(model=modelo, max_tokens=16, messages=[{"role": "user", "content": "Responde: ok"}])
        return
    from openai import OpenAI

    cli = OpenAI(base_url=aj.base_url, api_key=aj.api_key or "sin-clave", timeout=25, max_retries=0)
    kw: dict[str, Any] = {
        "model": modelo,
        "messages": [{"role": "user", "content": "Responde: ok"}],
        aj.token_param or "max_tokens": 32,
    }
    cli.chat.completions.create(**kw)


def comprobar(aj: Ajustes, modelo: str, descargados: list[str] | None = None) -> dict[str, Any]:
    modelo = (modelo or "").strip()
    t0 = time.perf_counter()
    if descargados is not None:
        # Ollama: no se llama al modelo (lo cargaría en la GPU); basta ver si está descargado.
        nombres = set(descargados) | {d.removesuffix(":latest") for d in descargados}
        estado = "disponible" if modelo in nombres or f"{modelo}:latest" in nombres else "no_descargado"
        detalle = "Descargado en el servidor local." if estado == "disponible" else _MENSAJES[estado]
        return {"modelo": modelo, "estado": estado, "detalle": detalle, "latencia_ms": 0}
    if not es_modelo_de_chat(modelo):
        return {"modelo": modelo, "estado": "incompatible", "detalle": _MENSAJES["incompatible"], "latencia_ms": 0}
    try:
        _ping(aj, modelo)
        estado, tecnico = "disponible", ""
    except Exception as e:  # noqa: BLE001 — se clasifica; nunca se expone la clave
        estado = clasificar_error(e)
        tecnico = str(e)[:240]
    out = {"modelo": modelo, "estado": estado, "detalle": _MENSAJES[estado],
           "latencia_ms": int((time.perf_counter() - t0) * 1000)}
    if tecnico and estado != "disponible":
        out["tecnico"] = tecnico
    return out


def comprobar_varios(aj: Ajustes, modelos: list[str], descargados: list[str] | None = None) -> list[dict[str, Any]]:
    unicos = list(dict.fromkeys(m.strip() for m in modelos if m and m.strip()))
    if not unicos:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(unicos))) as ex:
        return list(ex.map(lambda m: comprobar(aj, m, descargados), unicos))
