"""
Qué páginas de la plantilla entran en el SITREP (se elige en "Motor de IA").

La plantilla institucional tiene 6 páginas y cada una corresponde a una sección
de la síntesis (`llm/secciones.py`). La página 1 (portada con el resumen
ejecutivo) es obligatoria. Una página que se quita:
  - no la redacta la IA (en modo por secciones ni se pide; en modo completo se
    le indica que no la redacte) y sus datos se vacían igual por si acaso,
  - no aparece en el PDF ni en la vista del briefing,
  - queda anotada en `contenido.generacion.paginas_excluidas`, así cada versión
    recuerda con qué páginas se generó aunque la configuración cambie después.

La elección se guarda append-only en `sitrep_paginas` (migración 004) y el
cambio queda en el audit_log. Sin la tabla, entran todas las páginas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pagina:
    clave: str          # = clave de la sección en llm/secciones.py
    numero: int         # página de la plantilla (1..6)
    titulo: str
    descripcion: str
    obligatoria: bool = False


PAGINAS: tuple[Pagina, ...] = (
    Pagina("ejecutivo", 1, "Portada y resumen ejecutivo",
           "Resumen ejecutivo, situación, asuntos críticos y proyección 24-72 h.", obligatoria=True),
    Pagina("personal", 2, "Personal",
           "Parte de fuerza, SLC, macrozonas, catástrofe y unidades de emergencia."),
    Pagina("inteligencia", 3, "Inteligencia",
           "Incidentes, sistema de alerta y meteorología."),
    Pagina("operaciones_despliegue", 4, "Operaciones",
           "Catástrofe, relevos norte/sur, Antártica y operaciones en el extranjero."),
    Pagina("operaciones_terreno", 5, "Operaciones en terreno",
           "Guardián Soberano, unidades en terreno, traslados UAC y despliegue."),
    Pagina("logistica", 6, "Logística",
           "Operacionalidad y material NOP por unidad."),
)
POR_CLAVE = {p.clave: p for p in PAGINAS}

# Datos del contenido que alimentan cada página (para vaciarlos si se quita).
_DATOS: dict[str, tuple[str, ...]] = {
    "personal": ("personal",),
    "inteligencia": ("inteligencia",),
    "operaciones_despliegue": ("operaciones.ops_catastrofe", "operaciones.relevos_norte",
                               "operaciones.relevos_sur", "operaciones.ops_antartica",
                               "operaciones.ops_extranjero"),
    "operaciones_terreno": ("operaciones.guardian_soberano", "operaciones.unidades_terreno_kpi",
                            "operaciones.traslados_uac", "operaciones.unidades_terreno",
                            "operaciones.despliegue_mapa"),
    "logistica": ("logistica",),
}


class PaginasError(ValueError):
    pass


def normalizar(excluidas: Any) -> list[str]:
    """Lista válida y ordenada de páginas a quitar (nunca la obligatoria)."""
    if not excluidas:
        return []
    if not isinstance(excluidas, (list, tuple, set)):
        raise PaginasError("Se esperaba una lista de páginas")
    malas = [x for x in excluidas if x not in POR_CLAVE]
    if malas:
        raise PaginasError(f"Página desconocida: {', '.join(map(str, malas))}")
    if any(POR_CLAVE[x].obligatoria for x in excluidas):
        raise PaginasError("La portada con el resumen ejecutivo es obligatoria")
    return [p.clave for p in PAGINAS if p.clave in set(excluidas)]


def excluidas_de(contenido: dict[str, Any] | None) -> list[str]:
    """Páginas quitadas en una versión ya generada."""
    gen = (contenido or {}).get("generacion") or {}
    try:
        return normalizar(gen.get("paginas_excluidas") or [])
    except PaginasError:
        return []


def indices_pdf(excluidas: list[str]) -> list[int]:
    """Índices (0..5) de las diapositivas de la plantilla que se quitan."""
    return sorted(POR_CLAVE[c].numero - 1 for c in excluidas if c in POR_CLAVE)


def quitar(contenido: dict[str, Any], excluidas: list[str]) -> dict[str, Any]:
    """Vacía los datos de las páginas quitadas (y su trazabilidad) y lo anota."""
    pedidas = set(excluidas or [])
    excluidas = [p.clave for p in PAGINAS if p.clave in pedidas and not p.obligatoria]
    if not excluidas:
        return contenido
    rutas = [r for c in excluidas for r in _DATOS.get(c, ())]
    for ruta in rutas:
        partes = ruta.split(".")
        nodo = contenido
        for p in partes[:-1]:
            nodo = nodo.get(p) if isinstance(nodo, dict) else None
        if isinstance(nodo, dict) and partes[-1] in nodo:
            del nodo[partes[-1]]
    if isinstance(contenido.get("trazabilidad"), dict):
        contenido["trazabilidad"] = {
            k: v for k, v in contenido["trazabilidad"].items()
            if not any(k == r or k.startswith(r + ".") or k.startswith(r + "[") for r in rutas)
        }
    for clave in ("personal", "inteligencia", "operaciones", "logistica"):
        contenido.setdefault(clave, {})
    gen = contenido.setdefault("generacion", {})
    gen["paginas_excluidas"] = list(excluidas)
    return contenido


def instruccion(excluidas: list[str]) -> str:
    """Texto para el prompt de síntesis completa: no gastar tokens en lo quitado."""
    if not excluidas:
        return ""
    nombres = "; ".join(f"{POR_CLAVE[c].titulo} ({POR_CLAVE[c].descripcion})" for c in excluidas)
    return ("\nEl mando quitó estas partes del SITREP: NO las redactes y deja sus objetos vacíos ({}): "
            + nombres + ".")


# ---------------------------------------------------------------------------
#  Persistencia (append-only)
# ---------------------------------------------------------------------------
def leer(db: Session) -> dict[str, Any]:
    """Configuración vigente: {excluidas, migracion_aplicada, actualizado_en}."""
    from .models import SitrepPaginas

    try:
        fila = db.execute(select(SitrepPaginas).where(SitrepPaginas.vigente.is_(True))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 — migración 004 sin aplicar
        db.rollback()
        return {"excluidas": [], "migracion_aplicada": False, "actualizado_en": None}
    if fila is None:
        return {"excluidas": [], "migracion_aplicada": True, "actualizado_en": None}
    try:
        excl = normalizar(fila.excluidas or [])
    except PaginasError:
        excl = []
    return {"excluidas": excl, "migracion_aplicada": True,
            "actualizado_en": fila.creado_en.isoformat() if fila.creado_en else None}


def excluidas_vigentes(db: Session) -> list[str]:
    try:
        return leer(db)["excluidas"]
    except Exception:  # noqa: BLE001 — nunca impide generar
        logger.warning("No se pudo leer la selección de páginas del SITREP; entran todas")
        return []


def guardar(db: Session, excluidas: list[str], actor_id: str | None) -> list[str]:
    from datetime import datetime, timezone

    from .models import SitrepPaginas

    excl = normalizar(excluidas)
    db.execute(
        update(SitrepPaginas).where(SitrepPaginas.vigente.is_(True))
        .values(vigente=False, desactivado_en=datetime.now(timezone.utc))
    )
    db.add(SitrepPaginas(excluidas=excl, vigente=True, creado_por=actor_id))
    db.flush()
    return excl
