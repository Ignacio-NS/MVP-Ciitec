"""
Canal de progreso en vivo (RF/UX): el worker publica avances por Redis pub/sub
y el endpoint WebSocket los reenvía al navegador.

Canal: `task:{task_id}`. Mensajes JSON: {etapa, doc_actual, doc_nombre, total, pct, estado}.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import redis

from .config import settings


@lru_cache(maxsize=1)
def _redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def canal(task_id: str) -> str:
    return f"task:{task_id}"


def clave_ultimo(task_id: str) -> str:
    return f"task:{task_id}:ultimo"


def publicar(task_id: str, payload: dict[str, Any]) -> None:
    try:
        texto = json.dumps(payload, ensure_ascii=False)
        r = _redis()
        # Se guarda el último estado: si el navegador se reconecta (proxy que corta
        # el WebSocket, pestaña dormida) recibe dónde va el pipeline sin esperar.
        r.set(clave_ultimo(task_id), texto, ex=86400)
        r.publish(canal(task_id), texto)
    except Exception:
        # el progreso es informativo; nunca debe tumbar el pipeline
        pass
