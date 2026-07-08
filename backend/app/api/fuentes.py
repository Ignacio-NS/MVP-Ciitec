"""Router de fuentes (RF-001): carga, listado, metadata y descarga (gated)."""
from __future__ import annotations

import hashlib
import io
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..auth import rbac
from ..auth.deps import CurrentUser, get_current_user
from ..db import get_db
from ..models import Fuente
from .seguridad import exigir_nivel

router = APIRouter(prefix="/fuentes", tags=["fuentes"])

_EXT_TIPO = {
    ".pdf": "PDF",
    ".doc": "WORD", ".docx": "WORD",
    ".xls": "EXCEL", ".xlsx": "EXCEL", ".xlsm": "EXCEL",
    ".msg": "CORREO", ".eml": "CORREO",
    ".txt": "BITACORA", ".log": "BITACORA", ".csv": "BITACORA",
}


def _tipo(nombre: str) -> str:
    return _EXT_TIPO.get(os.path.splitext(nombre)[1].lower(), "OTRO")


def _fuente_dict(f: Fuente) -> dict:
    return {
        "id": str(f.id),
        "nombre_archivo": f.nombre_archivo,
        "tipo": f.tipo,
        "nivel_clasificacion": f.nivel_clasificacion,
        "unidad": f.unidad,
        "estado": f.estado,
        "subido_en": f.subido_en.isoformat() if f.subido_en else None,
    }


@router.post("")
async def subir(
    files: list[UploadFile] = File(...),
    nivel_clasificacion: str = Form("RESERVADO"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    storage.ensure_bucket()
    creadas = []
    for file in files:
        data = await file.read()
        sha = hashlib.sha256(data).hexdigest()

        # Dedup por contenido (RF-001): re-subir un archivo idéntico REUTILIZA su fuente en
        # lugar de crear una fila nueva. Sin esto, cada "Cargar → Generar" clonaba las 10
        # fuentes; como la generación por defecto corre sobre TODAS las fuentes, el pool de
        # hechos —y con él las inconsistencias DESACTUALIZADO— crecía en cada reporte.
        # Se acota a la unidad del usuario para no cruzar la segmentación RBAC (RNF-001).
        existente = db.execute(
            select(Fuente).where(Fuente.hash_sha256 == sha, Fuente.unidad == user.unidad)
        ).scalars().first()
        if existente is not None:
            # Se vuelve a marcar PENDIENTE para que la próxima generación la reprocese
            # (idempotente: reprocesar reemplaza sus hechos no referenciados).
            existente.estado = "PENDIENTE"
            existente.nivel_clasificacion = nivel_clasificacion
            db.commit()
            db.refresh(existente)
            creadas.append(_fuente_dict(existente))
            continue

        key = f"{uuid.uuid4()}/{file.filename}"
        storage.put_bytes(key, data, file.content_type or "application/octet-stream")
        f = Fuente(
            nombre_archivo=file.filename,
            tipo=_tipo(file.filename),
            mime=file.content_type,
            objeto_minio=key,
            hash_sha256=sha,
            nivel_clasificacion=nivel_clasificacion,
            unidad=user.unidad,  # la fuente queda asociada a la unidad de quien la sube (RNF-001)
            estado="PENDIENTE",
            subido_por=uuid.UUID(user.id),
        )
        db.add(f)
        db.commit()
        db.refresh(f)
        creadas.append(_fuente_dict(f))
    return {"fuentes": creadas}


@router.get("")
def listar(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Fuente).order_by(Fuente.subido_en.desc())
    # Segmentación por unidad (RNF-001): salvo roles transversales, solo se ven
    # las fuentes de la propia unidad (más las sin unidad asignada, legado).
    if not rbac.es_transversal(user.roles):
        q = q.where((Fuente.unidad == user.unidad) | (Fuente.unidad.is_(None)))
    filas = db.execute(q).scalars().all()
    return {"fuentes": [_fuente_dict(f) for f in filas]}


@router.get("/{fuente_id}")
def detalle(fuente_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(Fuente, uuid.UUID(fuente_id))
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fuente no encontrada")
    exigir_nivel(db, user, f.nivel_clasificacion, entidad_tipo="fuente", entidad_id=str(f.id), unidad_recurso=f.unidad)
    return _fuente_dict(f)


@router.get("/{fuente_id}/texto")
def texto(fuente_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Texto extraído de la fuente, para visualizarlo dentro de la app (trazabilidad RF-006).

    Gateado por nivel/unidad y auditado como CONSULTA_CLASIFICADA vía exigir_nivel.
    """
    f = db.get(Fuente, uuid.UUID(fuente_id))
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fuente no encontrada")
    exigir_nivel(db, user, f.nivel_clasificacion, entidad_tipo="fuente", entidad_id=str(f.id), unidad_recurso=f.unidad)
    return {
        "id": str(f.id),
        "nombre_archivo": f.nombre_archivo,
        "tipo": f.tipo,
        "nivel_clasificacion": f.nivel_clasificacion,
        "unidad": f.unidad,
        "estado": f.estado,
        "texto_extraido": f.texto_extraido or "",
    }


@router.get("/{fuente_id}/descargar")
def descargar(fuente_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(Fuente, uuid.UUID(fuente_id))
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fuente no encontrada")
    exigir_nivel(db, user, f.nivel_clasificacion, entidad_tipo="fuente", entidad_id=str(f.id), unidad_recurso=f.unidad)
    data = storage.get_bytes(f.objeto_minio)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=f.mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{f.nombre_archivo}"'},
    )
