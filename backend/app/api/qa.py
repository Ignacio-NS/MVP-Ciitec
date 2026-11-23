"""
Pruebas de QA de motores de IA (solo lectura): GET /qa/corridas y GET /qa/corridas/{id}.

Muestra en la interfaz los resultados que genera benchmark_llm (tiempo, calidad,
exactitud de cifras, costo y el SITREP de cada corrida) para analizarlos en equipo.
Mismos roles que ven la configuración del motor de IA.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from .. import qa_resultados
from ..auth import rbac
from ..auth.deps import CurrentUser, require_roles
from ..pipeline import exportacion
from ..schemas.api import ExportarIn

router = APIRouter(prefix="/qa", tags=["qa"])
_ver = require_roles(*rbac.ROLES_VER_CONFIG_IA)


@router.get("/corridas")
def corridas(user: CurrentUser = Depends(_ver)):
    return qa_resultados.listar()


@router.get("/corridas/{id_corrida}")
def corrida(id_corrida: str, user: CurrentUser = Depends(_ver)):
    d = qa_resultados.detalle(id_corrida)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Corrida no encontrada")
    return d


@router.post("/corridas/{id_corrida}/exportar")
def exportar(id_corrida: str, body: ExportarIn, user: CurrentUser = Depends(_ver)):
    """El SITREP de una corrida con la plantilla institucional (PDF, Word o texto), igual que
    la exportación de un briefing. No se guarda en MinIO ni en la BD: son datos de prueba."""
    d = qa_resultados.detalle(id_corrida)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Corrida no encontrada")
    if not d.get("sitrep"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta corrida no generó un SITREP")
    try:
        fecha = datetime.fromisoformat(d["inicio"]) if d.get("inicio") else datetime.now(timezone.utc)
    except ValueError:
        fecha = datetime.now(timezone.utc)
    titulo = f"SITREP de prueba - {d['motor']} - corrida {d['corrida']}"
    data, content_type, ext = exportacion.render(d["sitrep"], body.formato, titulo, fecha)
    nombre = f"QA_{id_corrida}.{ext}"
    return StreamingResponse(io.BytesIO(data), media_type=content_type,
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
