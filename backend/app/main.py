"""
FastAPI — Capa 2 (API). Monta routers, CORS, sesión sliding (RNF-001) y /health.

Nginx hace de reverse proxy + TLS y reescribe /api/ -> / hacia este servicio,
por eso los routers se montan sin el prefijo /api.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api import audit, auth, briefings, fuentes, ws
from .auth.tokens import decodificar_token, renovar_token
from .storage import ensure_bucket

app = FastAPI(title="Síntesis Automática de SITREP — CIITEC", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://localhost(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Token"],
)


@app.middleware("http")
async def sesion_sliding(request: Request, call_next):
    """Renueva el token en cada request válido (expiración por inactividad, RNF-001)."""
    response = await call_next(request)
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        payload = decodificar_token(authz[7:])
        if payload:
            response.headers["X-Session-Token"] = renovar_token(payload)
    return response


@app.on_event("startup")
def _startup():
    try:
        ensure_bucket()
    except Exception:
        # MinIO puede tardar en estar listo; el bucket también se asegura al subir.
        pass


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(fuentes.router)
app.include_router(briefings.router)
app.include_router(audit.router)
app.include_router(ws.router)
