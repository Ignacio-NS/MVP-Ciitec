"""Modelos Pydantic de request/response de la API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class LLMConfigIn(BaseModel):
    """Configuración del motor de IA enviada desde la interfaz de administración.

    `api_key`: None = conservar la clave ya guardada para ese proveedor (o usar la
    del .env); "" = borrar la guardada y usar la del .env; texto = clave nueva."""

    proveedor: str
    modelo: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    json_mode: bool | None = None
    temperature: str | None = None
    token_param: str | None = None
    extra_params: dict | None = None
    context_tokens: int | None = None
    timeout_s: float | None = None
    sintesis_modo: str | None = None   # auto | completa | secciones
    probar: bool = True     # probar la conexión antes de activar
    forzar: bool = False    # activar aunque la prueba falle


class LLMDisponibilidadIn(LLMConfigIn):
    """Modelos a comprobar (vacío = el modelo del formulario)."""

    modelos: list[str] = Field(default_factory=list, max_length=12)
