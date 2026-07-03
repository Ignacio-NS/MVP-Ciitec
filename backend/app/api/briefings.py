"""
Router de briefings: generación (RF-004), versionado (RF-007), point-in-time
(RF-009), diffs, aprobación, inconsistencias (RF-005), trazabilidad (RF-006) y
exportación (RF-008).
"""
from __future__ import annotations

import difflib
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .. import audit, storage
from ..auth import rbac
from ..auth.deps import CurrentUser, get_current_user, require_roles
from ..db import get_db
from ..models import (
    Briefing,
    BriefingVersion,
    Exportacion,
    Fuente,
    Hecho,
    Inconsistencia,
    VersionBulletHecho,
)
from ..pipeline import exportacion
from ..schemas.api import CrearBriefingIn, EditarVersionIn, ExportarIn
from ..worker import lanzar_generacion
from .seguridad import exigir_nivel

router = APIRouter(prefix="/briefings", tags=["briefings"])


def _hechos_detalle(db: Session, ids: list[str]) -> dict[str, dict]:
    """Resuelve hecho_ids → detalle legible (evento + archivo origen) en UNA consulta.

    Evita N+1 y permite que el front muestre texto y nombre de archivo en vez de UUIDs
    (inconsistencias RF-005, trazabilidad RF-006).
    """
    uids = []
    for x in ids:
        try:
            uids.append(uuid.UUID(str(x)))
        except (ValueError, AttributeError, TypeError):
            continue
    if not uids:
        return {}
    filas = db.execute(
        select(
            Hecho.id, Hecho.evento, Hecho.ocurrido_en, Hecho.texto_origen,
            Fuente.id.label("fuente_id"), Fuente.nombre_archivo,
        ).join(Fuente, Fuente.id == Hecho.fuente_id).where(Hecho.id.in_(uids))
    ).all()
    return {
        str(r.id): {
            "id": str(r.id),
            "evento": r.evento,
            "ocurrido_en": r.ocurrido_en.isoformat() if r.ocurrido_en else None,
            "texto_origen": r.texto_origen or "",
            "fuente_id": str(r.fuente_id),
            "fuente_nombre": r.nombre_archivo,
        }
        for r in filas
    }


def _version_activa(db: Session, briefing_id, at: datetime | None = None) -> BriefingVersion | None:
    q = select(BriefingVersion).where(BriefingVersion.briefing_id == briefing_id)
    if at is not None:
        q = q.where(BriefingVersion.creado_en <= at)
    return db.execute(q.order_by(desc(BriefingVersion.creado_en)).limit(1)).scalar_one_or_none()


# ---------------- Generación ----------------
@router.post("")
def crear(body: CrearBriefingIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.fuente_ids:
        # Solo se aceptan fuentes a las que el usuario tiene acceso por unidad (RNF-001).
        sel = db.execute(select(Fuente).where(Fuente.id.in_(body.fuente_ids))).scalars().all()
        for f in sel:
            if not rbac.unidad_ok(user.roles, user.unidad, f.unidad):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Fuente fuera de la unidad del usuario")
        fuente_ids = [str(f.id) for f in sel]
    else:
        q = select(Fuente.id).where(Fuente.estado != "ERROR")
        # Sin lista explícita: solo las fuentes de la propia unidad (salvo rol transversal).
        if not rbac.es_transversal(user.roles):
            q = q.where((Fuente.unidad == user.unidad) | (Fuente.unidad.is_(None)))
        fuente_ids = [str(fid) for fid in db.execute(q).scalars()]
    if not fuente_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No hay fuentes para procesar")

    briefing = Briefing(
        titulo=body.titulo,
        nivel_clasificacion=body.nivel_clasificacion,
        unidad=user.unidad,  # el briefing queda asociado a la unidad de su autor (RNF-001)
        periodo_desde=body.periodo_desde,
        periodo_hasta=body.periodo_hasta,
        creado_por=uuid.UUID(user.id),
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)

    task_id = str(uuid.uuid4())
    lanzar_generacion(
        briefing_id=str(briefing.id), fuente_ids=fuente_ids,
        parametros={"titulo": body.titulo}, task_id=task_id, generado_por=user.id,
    )
    return {"briefing_id": str(briefing.id), "task_id": task_id, "fuentes": len(fuente_ids)}


@router.get("")
def listar(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Briefing).order_by(desc(Briefing.creado_en))
    # Segmentación por unidad (RNF-001): salvo roles transversales, solo la propia unidad.
    if not rbac.es_transversal(user.roles):
        q = q.where((Briefing.unidad == user.unidad) | (Briefing.unidad.is_(None)))
    filas = db.execute(q).scalars().all()
    out = []
    for b in filas:
        v = _version_activa(db, b.id)
        out.append({
            "id": str(b.id), "titulo": b.titulo, "estado": b.estado,
            "nivel_clasificacion": b.nivel_clasificacion,
            "creado_en": b.creado_en.isoformat() if b.creado_en else None,
            "version_activa": v.numero_version if v else None,
        })
    return {"briefings": out}


@router.get("/{briefing_id}")
def detalle(briefing_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(Briefing, uuid.UUID(briefing_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)
    v = _version_activa(db, b.id)
    return {
        "id": str(b.id), "titulo": b.titulo, "estado": b.estado,
        "nivel_clasificacion": b.nivel_clasificacion,
        "version": v.numero_version if v else None,
        "contenido": v.contenido if v else None,
        "creado_en": b.creado_en.isoformat() if b.creado_en else None,
    }


# ---------------- Versiones (RF-007) y point-in-time (RF-009) ----------------
@router.get("/{briefing_id}/versiones")
def versiones(
    briefing_id: str,
    at: datetime | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = db.get(Briefing, uuid.UUID(briefing_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)

    if at is not None:
        # Reconstrucción a una hora pasada (RF-009)
        v = _version_activa(db, b.id, at=at)
        if v is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe versión activa en ese instante")
        audit.registrar(db, accion="RECONSTRUCCION", actor_id=user.id, entidad_tipo="briefing",
                        entidad_id=str(b.id), detalle={"at": at.isoformat(), "version": v.numero_version})
        return {"at": at.isoformat(), "version": v.numero_version, "contenido": v.contenido,
                "creado_en": v.creado_en.isoformat()}

    filas = db.execute(
        select(BriefingVersion).where(BriefingVersion.briefing_id == b.id).order_by(BriefingVersion.numero_version)
    ).scalars().all()
    return {"versiones": [{
        "id": str(v.id), "numero_version": v.numero_version,
        "comentario_cambio": v.comentario_cambio,
        "aprobado_por": str(v.aprobado_por) if v.aprobado_por else None,
        "aprobado_en": v.aprobado_en.isoformat() if v.aprobado_en else None,
        "creado_en": v.creado_en.isoformat() if v.creado_en else None,
    } for v in filas]}


@router.get("/{briefing_id}/versiones/{numero}")
def version_n(briefing_id: str, numero: int, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(Briefing, uuid.UUID(briefing_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)
    v = db.execute(select(BriefingVersion).where(
        BriefingVersion.briefing_id == b.id, BriefingVersion.numero_version == numero)).scalar_one_or_none()
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Versión no encontrada")
    return {"id": str(v.id), "numero_version": v.numero_version, "contenido": v.contenido,
            "creado_en": v.creado_en.isoformat() if v.creado_en else None}


@router.get("/{briefing_id}/diff/{a}/{b}")
def diff(briefing_id: str, a: int, b: int, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    br = db.get(Briefing, uuid.UUID(briefing_id))
    if br is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, br.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(br.id), unidad_recurso=br.unidad)

    def _contenido(n: int):
        v = db.execute(select(BriefingVersion).where(
            BriefingVersion.briefing_id == br.id, BriefingVersion.numero_version == n)).scalar_one_or_none()
        if v is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Versión {n} no existe")
        return json.dumps(v.contenido, ensure_ascii=False, indent=2).splitlines()

    izq, der = _contenido(a), _contenido(b)
    delta = list(difflib.unified_diff(izq, der, fromfile=f"v{a}", tofile=f"v{b}", lineterm=""))
    return {"desde": a, "hasta": b, "diff": delta}


# ---------------- Edición manual (RF-007) ----------------
@router.post("/{briefing_id}/versiones")
def editar_version(
    briefing_id: str,
    body: EditarVersionIn,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Guarda el contenido editado como una versión NUEVA (append-only, RF-007).

    Nunca se sobreescribe una versión existente: editar v2 y guardar produce v3.
    La trazabilidad bullet -> hecho se copia desde la versión base (RF-006).
    """
    b = db.get(Briefing, uuid.UUID(briefing_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)
    if not body.contenido:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El contenido editado no puede estar vacío")

    if body.base_version is not None:
        base = db.execute(select(BriefingVersion).where(
            BriefingVersion.briefing_id == b.id,
            BriefingVersion.numero_version == body.base_version)).scalar_one_or_none()
        if base is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Versión base {body.base_version} no existe")
    else:
        base = _version_activa(db, b.id)
    if base is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El briefing aún no tiene una versión que editar")

    ultima = db.execute(
        select(BriefingVersion).where(BriefingVersion.briefing_id == b.id)
        .order_by(desc(BriefingVersion.numero_version)).limit(1)
    ).scalar_one()
    version = BriefingVersion(
        briefing_id=b.id,
        numero_version=ultima.numero_version + 1,
        contenido=body.contenido,
        comentario_cambio=body.comentario or f"Edición manual (basada en v{base.numero_version})",
        fuentes_agregadas=base.fuentes_agregadas or [],
        generado_por=uuid.UUID(user.id),
    )
    db.add(version)
    db.flush()
    # La nueva versión conserva los vínculos bullet -> hecho de la versión base (RF-006).
    trazas = db.execute(select(VersionBulletHecho).where(VersionBulletHecho.version_id == base.id)).scalars().all()
    for t in trazas:
        db.add(VersionBulletHecho(version_id=version.id, bullet_key=t.bullet_key, hecho_id=t.hecho_id))
    b.estado = "BORRADOR"  # una edición posterior a la aprobación requiere re-aprobar
    db.commit()
    audit.registrar(db, accion="EDICION", actor_id=user.id, entidad_tipo="version",
                    entidad_id=str(version.id),
                    detalle={"version": version.numero_version, "base": base.numero_version},
                    nivel_afectado=b.nivel_clasificacion)
    return {"version_id": str(version.id), "numero_version": version.numero_version,
            "base": base.numero_version, "estado": b.estado}


# ---------------- Aprobación (RF-007) ----------------
@router.post("/versiones/{version_id}/aprobar")
def aprobar(
    version_id: str,
    user: CurrentUser = Depends(require_roles(*rbac.ROLES_APROBACION)),
    db: Session = Depends(get_db),
):
    v = db.get(BriefingVersion, uuid.UUID(version_id))
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Versión no encontrada")
    b = db.get(Briefing, v.briefing_id)
    # Aprobar exige acceso por nivel y unidad al briefing (RNF-001).
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)
    v.aprobado_por = uuid.UUID(user.id)
    v.aprobado_en = datetime.now(timezone.utc)
    b.estado = "APROBADO"
    db.commit()
    audit.registrar(db, accion="APROBACION", actor_id=user.id, entidad_tipo="version",
                    entidad_id=str(v.id), detalle={"version": v.numero_version})
    return {"ok": True, "version": v.numero_version, "estado": b.estado}


# ---------------- Inconsistencias (RF-005) ----------------
@router.get("/{briefing_id}/inconsistencias")
def inconsistencias(briefing_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(Briefing, uuid.UUID(briefing_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)
    filas = db.execute(select(Inconsistencia).where(Inconsistencia.briefing_id == uuid.UUID(briefing_id))).scalars().all()
    todos_ids = [hid for i in filas for hid in (i.hechos_involucrados or [])]
    detalle = _hechos_detalle(db, todos_ids)
    return {"inconsistencias": [{
        "id": str(i.id), "tipo": i.tipo, "severidad": i.severidad,
        "descripcion": i.descripcion, "hechos_involucrados": i.hechos_involucrados,
        "hechos": [detalle[str(h)] for h in (i.hechos_involucrados or []) if str(h) in detalle],
        "resuelto": i.resuelto,
    } for i in filas]}


# ---------------- Trazabilidad (RF-006) ----------------
@router.get("/{briefing_id}/trazabilidad")
def trazabilidad(briefing_id: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(Briefing, uuid.UUID(briefing_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)
    v = _version_activa(db, b.id)
    if v is None:
        return {"trazas": []}
    filas = db.execute(select(VersionBulletHecho).where(VersionBulletHecho.version_id == v.id)).scalars().all()
    detalle = _hechos_detalle(db, [str(t.hecho_id) for t in filas])
    return {"version": v.numero_version, "trazas": [
        {"bullet_key": t.bullet_key, "hecho_id": str(t.hecho_id), "hecho": detalle.get(str(t.hecho_id))}
        for t in filas
    ]}


# ---------------- Exportación (RF-008) ----------------
@router.post("/{briefing_id}/exportar")
def exportar(
    briefing_id: str,
    body: ExportarIn,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = db.get(Briefing, uuid.UUID(briefing_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing no encontrado")
    exigir_nivel(db, user, b.nivel_clasificacion, entidad_tipo="briefing", entidad_id=str(b.id), unidad_recurso=b.unidad)

    if body.version_id:
        v = db.get(BriefingVersion, uuid.UUID(body.version_id))
    else:
        v = _version_activa(db, b.id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay versión para exportar")

    data, content_type, ext = exportacion.render(v.contenido, body.formato, b.titulo, datetime.now(timezone.utc))

    key = f"export/{b.id}/v{v.numero_version}.{ext}"
    storage.put_bytes(key, data, content_type)
    db.add(Exportacion(
        version_id=v.id, formato=body.formato.upper(), objeto_minio=key,
        nivel_clasificacion=b.nivel_clasificacion, generado_por=uuid.UUID(user.id),
    ))
    db.commit()
    audit.registrar(db, accion="EXPORTACION", actor_id=user.id, entidad_tipo="briefing",
                    entidad_id=str(b.id), detalle={"formato": body.formato, "version": v.numero_version},
                    nivel_afectado=b.nivel_clasificacion)

    nombre = f"{b.titulo.replace(' ', '_')}_v{v.numero_version}.{ext}"
    return StreamingResponse(io.BytesIO(data), media_type=content_type,
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
