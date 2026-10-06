"""
Filtro 5 — SÍNTESIS (RF-004) + versionado/trazabilidad (RF-006, RF-007).

A partir de los hechos extraídos, el LLM genera el briefing institucional. Se
crea una NUEVA versión append-only y se persiste la trazabilidad bullet -> hecho.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..llm.provider import LLMProvider
from ..models import BriefingVersion, Fuente, Hecho, VersionBulletHecho


def _select_hechos(hechos: list[Hecho], limite: int) -> list[Hecho]:
    """Acota los hechos enviados a la síntesis para no exceder el contexto del LLM.

    Si hay más de `limite`, prioriza los más relevantes: estado ABIERTO/EN_CURSO
    primero, luego los más recientes por `ocurrido_en`.
    """
    if limite <= 0 or len(hechos) <= limite:
        return hechos
    prioridad = {"ABIERTO": 0, "EN_CURSO": 1}

    def clave(h: Hecho):
        p = prioridad.get((h.estado or "").upper(), 2)
        ts = h.ocurrido_en.timestamp() if h.ocurrido_en else float("-inf")
        return (p, -ts)  # menor prioridad primero; dentro, más reciente primero

    return sorted(hechos, key=clave)[:limite]


def _hechos_payload(hechos: list[Hecho]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(h.id),
            "evento": h.evento,
            "ocurrido_en": h.ocurrido_en.isoformat() if h.ocurrido_en else "",
            "ubicacion": h.ubicacion or "",
            "responsable": h.responsable or "",
            "impacto": h.impacto or "",
            "estado": h.estado or "",
        }
        for h in hechos
    ]


def contexto_fuentes(db: Session, fuente_ids: list[str]) -> str:
    """Texto acotado de las fuentes, con presupuesto POR archivo (para que TODAS aporten
    cifras) y el nombre del archivo antepuesto para poder atribuir cada dato (RF-004)."""
    filas = db.execute(
        select(Fuente.nombre_archivo, Fuente.texto_extraido).where(Fuente.id.in_(fuente_ids))
    ).all()
    por_fuente = settings.synth_max_chars_por_fuente
    bloques = [
        f"[{nombre}]\n{(texto or '')[:por_fuente]}"
        for nombre, texto in filas
        if texto
    ]
    return "\n---\n".join(bloques)[: settings.synth_max_contexto_chars]


def sintetizar(
    db: Session,
    *,
    briefing_id: str,
    hechos: list[Hecho],
    fuente_ids: list[str],
    provider: LLMProvider,
    generado_por: str | None,
    parametros: dict[str, Any] | None = None,
    comentario: str = "Generación automática",
) -> BriefingVersion:
    # Contexto de las fuentes (acotado) para que la síntesis pueda completar
    # las casillas numéricas institucionales que no son "hechos" (RF-004).
    params = dict(parametros or {})
    if fuente_ids:
        params["contexto_fuentes"] = contexto_fuentes(db, fuente_ids)

    hechos_sel = _select_hechos(hechos, settings.synth_max_hechos)
    contenido = provider.sintetizar_briefing(_hechos_payload(hechos_sel), params)

    # numero_version siguiente (append-only, RF-007)
    actual = db.execute(
        select(func.coalesce(func.max(BriefingVersion.numero_version), 0)).where(
            BriefingVersion.briefing_id == briefing_id
        )
    ).scalar_one()

    # Las hojas adicionales las agrega el usuario (no las genera la síntesis): al regenerar el
    # briefing se arrastran desde la última versión para no perderlas.
    previa = (
        db.execute(
            select(BriefingVersion)
            .where(BriefingVersion.briefing_id == briefing_id, BriefingVersion.numero_version == actual)
        ).scalar_one_or_none()
        if actual
        else None
    )
    hojas_previas = (previa.contenido or {}).get("hojas_adicionales") if previa else None
    if hojas_previas:
        contenido["hojas_adicionales"] = hojas_previas

    version = BriefingVersion(
        briefing_id=briefing_id,
        numero_version=actual + 1,
        contenido=contenido,
        comentario_cambio=comentario,
        fuentes_agregadas=fuente_ids,
        generado_por=generado_por,
    )
    db.add(version)
    db.flush()  # obtener version.id

    # Trazabilidad bullet -> hecho (RF-006)
    ids_validos = {str(h.id) for h in hechos}
    traza = contenido.get("trazabilidad", {}) or {}
    vistos: set[tuple[str, str]] = set()
    for bullet_key, hecho_ids in traza.items():
        for hid in hecho_ids or []:
            hid = str(hid)
            if hid in ids_validos and (bullet_key, hid) not in vistos:
                vistos.add((bullet_key, hid))
                db.add(
                    VersionBulletHecho(
                        version_id=version.id,
                        bullet_key=bullet_key[:300],
                        hecho_id=hid,
                    )
                )

    # Trazabilidad de las hojas arrastradas (claves 'hoja:<id>:b<n>', RF-006).
    if hojas_previas:
        trazas_hoja = db.execute(
            select(VersionBulletHecho).where(
                VersionBulletHecho.version_id == previa.id,
                VersionBulletHecho.bullet_key.like("hoja:%"),
            )
        ).scalars().all()
        for t in trazas_hoja:
            db.add(VersionBulletHecho(version_id=version.id, bullet_key=t.bullet_key, hecho_id=t.hecho_id))
    return version
