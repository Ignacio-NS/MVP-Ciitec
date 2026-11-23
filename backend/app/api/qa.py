"""
Pruebas de QA de motores de IA (solo lectura): GET /qa/corridas y GET /qa/corridas/{id}.

Muestra en la interfaz los resultados que genera benchmark_llm (tiempo, calidad,
exactitud de cifras, costo y el SITREP de cada corrida) para analizarlos en equipo.
Mismos roles que ven la configuración del motor de IA.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from .. import qa_resultados
from ..auth import rbac
from ..auth.deps import CurrentUser, require_roles

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
