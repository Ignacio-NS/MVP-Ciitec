"""
Worker Celery — Capa 3. Orquesta el pipeline en paralelo (RNF-004: 50 docs < 3 min).

Patrón:  chord( group(procesar_fuente x N) )( consolidar_briefing )
  - cada documento se procesa en paralelo (ingesta→extracción→embeddings),
  - cuando TODOS terminan, el callback consolida: detección cross-doc + síntesis.

El progreso se publica por Redis pub/sub (canal task:{task_id}) y el WebSocket
lo reenvía al navegador.
"""
from __future__ import annotations

from typing import Any

from celery import Celery, chord
from celery.schedules import crontab
from sqlalchemy import select

from . import audit, progress, storage
from .config import settings
from .db import SessionLocal
from .llm.provider import get_llm_provider
from .models import Fuente, Hecho, Inconsistencia, VersionBulletHecho
from .pipeline import deteccion, extraccion, ingesta, sintesis

celery_app = Celery(
    "briefings",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    beat_schedule={
        "purga-retencion-audit": {
            "task": "app.worker.purga_retencion",
            "schedule": crontab(hour=3, minute=0),  # diaria 03:00 UTC
        }
    },
)


@celery_app.task(name="app.worker.procesar_fuente")
def procesar_fuente(fuente_id: str, task_id: str) -> str | None:
    """Filtros 1–3 por documento: ingesta → extracción → embeddings (RF-001/002/003)."""
    with SessionLocal() as db:
        fuente = db.get(Fuente, fuente_id)
        if fuente is None:
            return None
        try:
            fuente.estado = "PROCESANDO"
            db.commit()
            progress.publicar(task_id, {"etapa": "procesando", "doc_nombre": fuente.nombre_archivo})

            data = storage.get_bytes(fuente.objeto_minio)
            texto = ingesta.extraer_texto(data, fuente.tipo, fuente.nombre_archivo)
            fuente.texto_extraido = texto

            # Idempotencia (RF-003): reprocesar una fuente REEMPLAZA sus hechos en vez de
            # acumularlos. Evita que un reintento/redelivery de Celery multiplique los hechos
            # y dispare falsos DUPLICADO/DESACTUALIZADO/INCOMPLETO. No se tocan los hechos ya
            # vinculados a una versión: su trazabilidad (RF-006) es append-only e inmutable.
            previos = [hid for (hid,) in db.query(Hecho.id).filter(Hecho.fuente_id == fuente.id).all()]
            if previos:
                referenciados = {
                    hid
                    for (hid,) in db.query(VersionBulletHecho.hecho_id)
                    .filter(VersionBulletHecho.hecho_id.in_(previos))
                    .all()
                }
                borrables = [hid for hid in previos if hid not in referenciados]
                if borrables:
                    db.query(Hecho).filter(Hecho.id.in_(borrables)).delete(synchronize_session=False)

            provider = get_llm_provider()
            for h in extraccion.extraer(texto, provider):
                db.add(Hecho(fuente_id=fuente.id, **h))

            fuente.estado = "PROCESADO"
            db.commit()
            audit.registrar(
                db, accion="INGESTA", actor_id=str(fuente.subido_por) if fuente.subido_por else None,
                entidad_tipo="fuente", entidad_id=str(fuente.id),
                detalle={"nombre": fuente.nombre_archivo}, nivel_afectado=fuente.nivel_clasificacion,
            )
            progress.publicar(task_id, {"etapa": "documento_ok", "doc_nombre": fuente.nombre_archivo})
            return str(fuente.id)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            fuente = db.get(Fuente, fuente_id)
            if fuente:
                fuente.estado = "ERROR"
                fuente.metadatos = {**(fuente.metadatos or {}), "error": str(e)[:500]}
                db.commit()
            progress.publicar(task_id, {"etapa": "documento_error", "doc_nombre": fuente_id, "error": str(e)[:200]})
            return None


@celery_app.task(name="app.worker.consolidar_briefing")
def consolidar_briefing(
    fuente_ids: list[str | None],
    briefing_id: str,
    parametros: dict[str, Any],
    task_id: str,
    generado_por: str | None,
) -> dict[str, Any]:
    """Filtros 4–5 (cross-doc): detección de inconsistencias + síntesis (RF-004/005/006/007)."""
    ids = [fid for fid in fuente_ids if fid]
    with SessionLocal() as db:
        # Solo los hechos de la extracción ACTUAL: se excluyen los que quedaron ligados a
        # una versión previa (VersionBulletHecho), que se conservan inmutables solo por
        # trazabilidad (RF-006). Al reprocesar, cada fuente re-extrae esos mismos hechos como
        # filas nuevas; contar además las copias históricas inflaba DESACTUALIZADO/DUPLICADO y
        # rompía la idempotencia (el mismo lote regenerado daba más inconsistencias cada vez).
        hechos = (
            db.query(Hecho)
            .filter(Hecho.fuente_id.in_(ids), Hecho.id.notin_(select(VersionBulletHecho.hecho_id)))
            .all()
            if ids
            else []
        )
        provider = get_llm_provider()

        progress.publicar(task_id, {"etapa": "detectando", "total_hechos": len(hechos)})
        inconsistencias, hechos_unicos = deteccion.detectar(db, hechos, provider)
        for inc in inconsistencias:
            db.add(
                Inconsistencia(
                    briefing_id=briefing_id,
                    tipo=inc["tipo"],
                    severidad=inc["severidad"],
                    descripcion=inc["descripcion"],
                    hechos_involucrados=inc["hechos_involucrados"],
                )
            )
        db.commit()

        progress.publicar(task_id, {"etapa": "sintetizando"})
        try:
            # Se sintetiza sobre los hechos ya deduplicados (un representante por clúster),
            # para que el LLM no reciba copias casi idénticas del mismo dato.
            version = sintesis.sintetizar(
                db, briefing_id=briefing_id, hechos=hechos_unicos, fuente_ids=ids,
                provider=provider, generado_por=generado_por, parametros=parametros,
            )
            db.commit()
        except Exception as e:  # noqa: BLE001 — p.ej. LLM sin clave / falla de red
            db.rollback()
            progress.publicar(task_id, {"etapa": "error", "briefing_id": briefing_id, "error": str(e)[:200]})
            return {"briefing_id": briefing_id, "error": str(e)[:200]}

        audit.registrar(
            db, accion="GENERACION", actor_id=generado_por,
            entidad_tipo="briefing", entidad_id=briefing_id,
            detalle={"version": version.numero_version, "fuentes": len(ids)},
        )
        progress.publicar(
            task_id,
            {"etapa": "completado", "briefing_id": briefing_id, "version": version.numero_version},
        )
        return {"briefing_id": briefing_id, "version": version.numero_version, "fuentes": len(ids)}


def lanzar_generacion(
    *, briefing_id: str, fuente_ids: list[str], parametros: dict[str, Any], task_id: str, generado_por: str | None
) -> None:
    """Construye y dispara el chord (paralelo) para generar un briefing."""
    header = [procesar_fuente.s(str(fid), task_id) for fid in fuente_ids]
    callback = consolidar_briefing.s(briefing_id, parametros, task_id, generado_por)
    chord(header)(callback)


@celery_app.task(name="app.worker.purga_retencion")
def purga_retencion() -> dict:
    from . import retention

    return retention.purgar()
