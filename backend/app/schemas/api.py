"""Modelos Pydantic de request/response de la API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class UsuarioOut(BaseModel):
    id: str
    username: str
    nombre: str
    unidad: str | None = None
    nivel_habilitacion: str
    roles: list[str] = []


class LoginOut(BaseModel):
    token: str
    usuario: UsuarioOut


class CrearBriefingIn(BaseModel):
    titulo: str
    fuente_ids: list[str] | None = None
    nivel_clasificacion: str = "RESERVADO"
    periodo_desde: datetime | None = None
    periodo_hasta: datetime | None = None


class ExportarIn(BaseModel):
    formato: str = "PDF"  # PDF | WORD | TEXTO
    version_id: str | None = None


class EditarVersionIn(BaseModel):
    """Edición manual del reporte: el contenido editado se guarda como versión nueva (RF-007)."""
    contenido: dict
    base_version: int | None = None  # versión desde la que se editó (default: la activa)
    comentario: str | None = None
