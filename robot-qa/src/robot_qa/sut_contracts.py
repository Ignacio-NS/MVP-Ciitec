"""Reusa los contratos Pydantic reales del SUT en vez de duplicarlos.

`backend/app/__init__.py` y `backend/app/schemas/__init__.py` estan vacios y
`app/schemas/llm.py` solo depende de pydantic, asi que se puede importar de
forma aislada (sin FastAPI, SQLAlchemy, LDAP ni Celery) agregando `backend/`
al sys.path. Asi el evaluador `schema` valida contra el MISMO `BriefingOut`
que usa `pipeline/sintesis.py` para validar la salida del LLM: si el
contrato cambia en el backend, el robot lo detecta sin que nadie tenga que
recordar mantener una copia sincronizada.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3] / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.schemas.llm import BriefingOut, HechosResponse  # noqa: E402

__all__ = ["BriefingOut", "HechosResponse"]
