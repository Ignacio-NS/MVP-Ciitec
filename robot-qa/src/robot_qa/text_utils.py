"""Utilidades de texto compartidas por varios evaluadores."""
from __future__ import annotations

import unicodedata
from typing import Any


def normalize(s: str) -> str:
    """minusculas + sin acentos, para comparar texto generado por un LLM."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def flatten_text(obj: Any) -> str:
    """Aplana un dict/list/str anidado (el 'contenido' del briefing) a un solo texto buscable."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float, bool)):
        return str(obj)
    if isinstance(obj, dict):
        return " ".join(flatten_text(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return " ".join(flatten_text(v) for v in obj)
    return str(obj)
