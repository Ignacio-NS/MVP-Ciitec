"""
Filtro 3 — EXTRACCIÓN (RF-003) + embeddings (RF-005).

Llama al LLM (vía la abstracción) para obtener hechos estructurados y, para cada
uno, normaliza (RF-002) y calcula su embedding local (sentence-transformers).
Devuelve dicts listos para persistir como filas de `hechos`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import embeddings
from ..llm import presupuesto
from ..llm.provider import LLMProvider
from . import normalizacion


def _texto_canonico(h: dict[str, Any]) -> str:
    """Texto representativo del hecho para el embedding de duplicados (RF-005)."""
    return " | ".join(
        str(h.get(k) or "")
        for k in ("evento", "ubicacion", "responsable", "impacto")
    )


def _a_datetime(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _extraer_crudos(texto: str, provider: LLMProvider) -> list[dict[str, Any]]:
    """Llama al LLM; si el documento no cabe en la ventana del modelo, lo parte.

    Con LLM_CONTEXT_TOKENS declarado (típico de modelos locales) un documento
    largo se procesa por fragmentos con solape; los hechos repetidos por el
    solape (mismo evento y misma cita textual) se descartan."""
    aj = getattr(provider, "aj", None)
    max_chars = presupuesto.max_chars_extraccion(aj) if aj is not None else 0
    trozos = presupuesto.fragmentar(texto, max_chars)
    if len(trozos) == 1:
        return provider.extraer_hechos(texto)
    vistos: set[tuple[str, str]] = set()
    crudos: list[dict[str, Any]] = []
    for trozo in trozos:
        for h in provider.extraer_hechos(trozo):
            clave = (str(h.get("evento", "")).strip().lower(), str(h.get("texto_origen", "")).strip().lower())
            if clave in vistos:
                continue
            vistos.add(clave)
            crudos.append(h)
    return crudos


def extraer(texto: str, provider: LLMProvider) -> list[dict[str, Any]]:
    """Extrae hechos del texto y los deja listos para persistir."""
    crudos = _extraer_crudos(texto, provider)
    resultado: list[dict[str, Any]] = []
    for h in crudos:
        normalizado = normalizacion.normalizar_hecho(h)
        resultado.append(
            {
                "evento": h.get("evento", "").strip(),
                "ocurrido_en": _a_datetime(normalizado.get("fecha_iso")),
                "ubicacion": h.get("ubicacion") or None,
                "responsable": h.get("responsable") or None,
                "impacto": h.get("impacto") or None,
                "estado": h.get("estado") or "ABIERTO",
                "texto_origen": h.get("texto_origen") or None,
                "normalizado": normalizado,
                "embedding": embeddings.embed(_texto_canonico(h)),
                "confianza": 0.9,  # heurística; el LLM no expone score
            }
        )
    return resultado
