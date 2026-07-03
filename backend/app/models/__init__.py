"""
Modelos ORM mapeados 1:1 al esquema de `db/schema.sql`.

No se hace create_all: las tablas y los tipos ENUM ya existen (los crea el
script de init de Postgres). Por eso los Enum usan create_type=False.

Columnas sensibles (texto extraído de la fuente y cita textual del hecho) usan
`EncryptedText` → cifrado en reposo transparente (RNF-002).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

from ..crypto import EncryptedText
from ..db import Base

# ---- ENUM existentes en la BD (no recrear) ----
NivelClasificacion = ENUM("PUBLICO", "RESERVADO", "SECRETO", name="nivel_clasificacion", create_type=False)
TipoFuente = ENUM("PDF", "WORD", "EXCEL", "CORREO", "BITACORA", "OTRO", name="tipo_fuente", create_type=False)
EstadoProcesamiento = ENUM("PENDIENTE", "PROCESANDO", "PROCESADO", "ERROR", name="estado_procesamiento", create_type=False)
EstadoHecho = ENUM("ABIERTO", "EN_CURSO", "CERRADO", name="estado_hecho", create_type=False)
EstadoBriefing = ENUM("BORRADOR", "APROBADO", name="estado_briefing", create_type=False)
TipoInconsistencia = ENUM("DUPLICADO", "CONTRADICCION", "DESACTUALIZADO", "INCOMPLETO", name="tipo_inconsistencia", create_type=False)
FormatoExport = ENUM("PDF", "WORD", "TEXTO", name="formato_export", create_type=False)
AccionAudit = ENUM(
    "LOGIN", "INGESTA", "GENERACION", "EDICION", "APROBACION", "EXPORTACION",
    "CONSULTA_CLASIFICADA", "RECONSTRUCCION",
    name="accion_audit", create_type=False,
)


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(Text, nullable=False, unique=True)
    nombre = Column(Text, nullable=False)
    unidad = Column(Text)
    nivel_habilitacion = Column(NivelClasificacion, nullable=False, default="PUBLICO")
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Rol(Base):
    __tablename__ = "roles"
    id = Column(SmallInteger, primary_key=True)
    nombre = Column(Text, nullable=False, unique=True)


class UsuarioRol(Base):
    __tablename__ = "usuario_roles"
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    rol_id = Column(SmallInteger, ForeignKey("roles.id"), primary_key=True)


class Fuente(Base):
    __tablename__ = "fuentes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre_archivo = Column(Text, nullable=False)
    tipo = Column(TipoFuente, nullable=False)
    mime = Column(Text)
    objeto_minio = Column(Text, nullable=False)
    hash_sha256 = Column(Text, nullable=False)
    nivel_clasificacion = Column(NivelClasificacion, nullable=False, default="RESERVADO")
    unidad = Column(Text)  # unidad propietaria (RBAC por unidad, RNF-001)
    timestamp_fuente = Column(DateTime(timezone=True))
    texto_extraido = Column(EncryptedText)  # cifrado en reposo (RNF-002)
    metadatos = Column("metadata", JSONB, nullable=False, default=dict)
    estado = Column(EstadoProcesamiento, nullable=False, default="PENDIENTE")
    subido_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    subido_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Hecho(Base):
    __tablename__ = "hechos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fuente_id = Column(UUID(as_uuid=True), ForeignKey("fuentes.id", ondelete="CASCADE"), nullable=False)
    evento = Column(Text, nullable=False)
    ocurrido_en = Column(DateTime(timezone=True))
    ubicacion = Column(Text)
    responsable = Column(Text)
    impacto = Column(Text)
    estado = Column(EstadoHecho)
    texto_origen = Column(EncryptedText)  # cita textual, cifrada en reposo (RNF-002, RF-006)
    ubicacion_origen = Column(JSONB)
    normalizado = Column(JSONB, nullable=False, default=dict)
    confianza = Column(Float)
    embedding = Column(Vector(384))
    creado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Briefing(Base):
    __tablename__ = "briefings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titulo = Column(Text, nullable=False)
    periodo_desde = Column(DateTime(timezone=True))
    periodo_hasta = Column(DateTime(timezone=True))
    nivel_clasificacion = Column(NivelClasificacion, nullable=False, default="RESERVADO")
    unidad = Column(Text)  # unidad propietaria (RBAC por unidad, RNF-001)
    estado = Column(EstadoBriefing, nullable=False, default="BORRADOR")
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    creado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BriefingVersion(Base):
    __tablename__ = "briefing_versiones"
    __table_args__ = (UniqueConstraint("briefing_id", "numero_version"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    briefing_id = Column(UUID(as_uuid=True), ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False)
    numero_version = Column(Integer, nullable=False)
    contenido = Column(JSONB, nullable=False)
    comentario_cambio = Column(Text)
    fuentes_agregadas = Column(JSONB, nullable=False, default=list)
    generado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    aprobado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    aprobado_en = Column(DateTime(timezone=True))
    creado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VersionBulletHecho(Base):
    __tablename__ = "version_bullet_hechos"
    version_id = Column(UUID(as_uuid=True), ForeignKey("briefing_versiones.id", ondelete="CASCADE"), primary_key=True)
    bullet_key = Column(Text, primary_key=True)
    hecho_id = Column(UUID(as_uuid=True), ForeignKey("hechos.id"), primary_key=True)


class Inconsistencia(Base):
    __tablename__ = "inconsistencias"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    briefing_id = Column(UUID(as_uuid=True), ForeignKey("briefings.id", ondelete="CASCADE"))
    tipo = Column(TipoInconsistencia, nullable=False)
    severidad = Column(SmallInteger, nullable=False, default=1)
    descripcion = Column(Text, nullable=False)
    hechos_involucrados = Column(JSONB, nullable=False, default=list)
    resuelto = Column(Boolean, nullable=False, default=False)
    detectado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Exportacion(Base):
    __tablename__ = "exportaciones"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id = Column(UUID(as_uuid=True), ForeignKey("briefing_versiones.id"), nullable=False)
    formato = Column(FormatoExport, nullable=False)
    objeto_minio = Column(Text, nullable=False)
    nivel_clasificacion = Column(NivelClasificacion, nullable=False)
    generado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    generado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    accion = Column(AccionAudit, nullable=False)
    entidad_tipo = Column(Text)
    entidad_id = Column(Text)
    detalle = Column(JSONB, nullable=False, default=dict)
    nivel_afectado = Column(NivelClasificacion)
    ocurrido_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    hash_anterior = Column(Text)
    hash_actual = Column(Text)


__all__ = [
    "Usuario", "Rol", "UsuarioRol", "Fuente", "Hecho", "Briefing",
    "BriefingVersion", "VersionBulletHecho", "Inconsistencia", "Exportacion",
    "AuditLog",
]
