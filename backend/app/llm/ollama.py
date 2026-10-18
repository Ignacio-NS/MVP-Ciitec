"""
Descarga de modelos en un servidor Ollama de la red institucional.

Para que el administrador pueda usar cualquier modelo local sin entrar al
servidor, la interfaz puede pedirle a Ollama que descargue uno (`/api/pull`).
Solo aplica a Ollama: vLLM carga su modelo al iniciar y no admite descargas en
caliente. Con la red sin salida a internet la descarga fallará: en ese caso los
modelos se copian al servidor por el procedimiento de ops (`ollama pull` en un
equipo con salida y traslado del directorio de modelos).
"""
from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .provider import LLMError


def raiz(base_url: str) -> str:
    """http://host:11434/v1 -> http://host:11434 (la API nativa de Ollama no va bajo /v1)."""
    u = (base_url or "").rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3]
    if urlparse(u).scheme not in ("http", "https"):
        raise LLMError(f"URL inválida para Ollama: {base_url!r}")
    return u


def version(base_url: str, timeout: float = 5.0) -> str | None:
    """Versión de Ollama, o None si el servidor no es Ollama (p.ej. vLLM)."""
    try:
        r = httpx.get(f"{raiz(base_url)}/api/version", timeout=timeout)
        if r.status_code == 200:
            return str(r.json().get("version") or "?")
    except Exception:  # noqa: BLE001
        return None
    return None


def descargar(
    base_url: str,
    modelo: str,
    al_avanzar: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Descarga `modelo` en el Ollama de `base_url`, informando el avance (0-100)."""
    modelo = (modelo or "").strip()
    if not modelo:
        raise LLMError("Indique el nombre del modelo a descargar (p.ej. qwen3.8:27b)")
    if version(base_url) is None:
        raise LLMError(
            "El servidor del modelo local no es Ollama (o no responde). vLLM carga su modelo al "
            "iniciar: para cambiarlo hay que reiniciar vLLM con otro modelo."
        )
    ultimo: dict[str, Any] = {}
    with httpx.stream(
        "POST", f"{raiz(base_url)}/api/pull", json={"model": modelo, "stream": True},
        timeout=httpx.Timeout(30.0, read=None),
    ) as r:
        if r.status_code != 200:
            raise LLMError(f"Ollama rechazó la descarga ({r.status_code}): {r.read().decode()[:300]}")
        for linea in r.iter_lines():
            if not linea.strip():
                continue
            ev = json.loads(linea)
            if ev.get("error"):
                raise LLMError(f"Ollama no pudo descargar '{modelo}': {ev['error']}")
            total, hecho = ev.get("total") or 0, ev.get("completed") or 0
            ultimo = {
                "estado": ev.get("status", ""),
                "pct": int(hecho * 100 / total) if total else None,
                "descargado_mb": round(hecho / 1e6) if total else None,
                "total_mb": round(total / 1e6) if total else None,
            }
            if al_avanzar:
                al_avanzar(ultimo)
    if ultimo.get("estado") != "success":
        raise LLMError(f"La descarga de '{modelo}' terminó sin confirmar ({ultimo.get('estado') or 'sin estado'})")
    return {"modelo": modelo, "estado": "descargado"}
