"""
Síntesis del SITREP POR SECCIONES.

El briefing institucional completo es un JSON grande (6 páginas). Los modelos
grandes lo redactan de una vez, pero un modelo chico o local con poca ventana
de contexto suele cortarse o devolver una estructura incompleta. Para que
cualquier modelo sirva, el mismo briefing se puede redactar en 6 llamadas
pequeñas (una por sección) y luego unir el resultado.

Cada sección recibe los MISMOS hechos y el mismo contexto de fuentes, y devuelve
solo su parte del JSON más su trazabilidad (rutas completas, p.ej.
"personal.slc.total"). El resultado unido pasa por la misma validación Pydantic
que la síntesis completa.

Política ante fallas: la sección EJECUTIVA es obligatoria (sin ella no hay
SITREP). Si otra sección falla, queda vacía ("-.-" en la plantilla) y se deja
constancia en `generacion.avisos`, que la interfaz muestra en la versión: el
documento nunca aparenta estar completo cuando no lo está.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CABECERA = """Eres un asesor de operaciones del Ejército de Chile. A partir de los HECHOS ya
extraídos (cada uno con su id) y del "contexto_fuentes" de "parametros" (texto de los documentos),
redacta SOLO la sección {titulo} de un briefing operacional institucional.
Responde SOLO con un JSON válido (sin preámbulo, sin markdown) con esta estructura exacta:
{esquema}
"""

_REGLAS_COMUNES = """Reglas: usa SOLO datos presentes en los hechos o en el contexto; NO inventes cifras.
Donde no haya dato, usa "-.-" (o una lista vacía []). Si en el contexto aparecen cifras o datos de esta
sección, ÚSALOS para completar las casillas. En "trazabilidad" la clave es la ruta completa del dato
(p.ej. "{ejemplo}") y el valor, la lista de ids de los hechos que lo respaldan (solo ids existentes)."""


@dataclass(frozen=True)
class Seccion:
    clave: str        # identificador interno
    titulo: str       # cómo se nombra en el prompt y en los avisos
    esquema: str      # JSON de ejemplo que debe devolver
    ejemplo_ruta: str
    requerido: str    # clave de nivel superior que la respuesta debe traer
    reglas: str = ""
    obligatoria: bool = False


SECCIONES: tuple[Seccion, ...] = (
    Seccion(
        clave="ejecutivo",
        requerido="resumen_ejecutivo",
        titulo="RESUMEN EJECUTIVO Y SITUACIÓN",
        obligatoria=True,
        ejemplo_ruta="resumen_ejecutivo[0]",
        esquema="""{
  "resumen_ejecutivo": ["5 a 10 bullets ejecutivos"],
  "asuntos_criticos": [{"asunto":"...","impacto":"...","responsable":"..."}],
  "proyeccion_24_72h": "proyección de las próximas 24 a 72 horas",
  "situacion": {"resumen":"panorama operacional general en 2-4 frases","aspectos":["aspecto relevante","..."]},
  "trazabilidad": {"resumen_ejecutivo[0]": ["id-de-hecho"]}
}""",
        reglas="Mantén entre 5 y 10 bullets en resumen_ejecutivo, en terminología institucional.",
    ),
    Seccion(
        clave="personal",
        requerido="personal",
        titulo="PERSONAL",
        ejemplo_ruta="personal.parte_fuerza_institucional.total",
        esquema="""{
  "personal": {
    "parte_fuerza_institucional": {"OF":"-.-","SOF":"-.-","ECP":"-.-","SLTP":"-.-","ESCMIL":"-.-","ESCSOF":"-.-","ESCSERV":"-.-","personal_civil":"-.-","SLC":"-.-","total":"-.-"},
    "slc": {"clase_2006":"-.-","clase_2007":"-.-","total":"-.-"},
    "macrozonas": [{"zona":"...","fuerza":"-.-","forman":"-.-","faltan":"-.-"}],
    "catastrofe": {"fuerza":"-.-","forman":"-.-","faltan":"-.-"},
    "unidades_emergencia": {"ufec":"-.-","brife":"-.-","parme":"-.-"}
  },
  "trazabilidad": {}
}""",
        reglas="Incluye personal OF/SOF/ECP/total, fuerzas por macrozona y unidades de emergencia UFEC/BRIFE/PARME.",
    ),
    Seccion(
        clave="inteligencia",
        requerido="inteligencia",
        titulo="INTELIGENCIA (INCIDENTES Y METEOROLOGÍA)",
        ejemplo_ruta="inteligencia.incidentes_institucionales[0]",
        esquema="""{
  "inteligencia": {
    "incidentes_institucionales": [{"tipo":"...","descripcion":"..."}],
    "incidentes_mootw": [{"tipo":"...","unidad":"...","descripcion":"..."}],
    "sistema_alerta": [{"alerta":"...","area":"...","unidad_asociada":"...","apreciacion":"..."}],
    "analisis_meteo": "...",
    "proyeccion_meteo_48h": "..."
  },
  "trazabilidad": {}
}""",
        reglas="Resume los incidentes y la meteorología (análisis y proyección a 48 h) que aparezcan.",
    ),
    Seccion(
        clave="operaciones_despliegue",
        requerido="operaciones",
        titulo="OPERACIONES (CATÁSTROFE, RELEVOS, ANTÁRTICA Y EXTRANJERO)",
        ejemplo_ruta="operaciones.ops_catastrofe[0]",
        esquema="""{
  "operaciones": {
    "ops_catastrofe": [{"cantidad":"-.-","tipo":"...","unidad_origen":"...","zona_empleo":"...","inicio_empleo":"..."}],
    "relevos_norte": [{"n":"...","fecha":"...","jaf":"...","unidades":"...","periodo":"..."}],
    "relevos_sur": [{"n":"...","fecha":"...","ft":"...","unidades":"...","periodo":"..."}],
    "ops_antartica": [{"bae":"...","dotacion_estival":"-.-","cpccgu":"..."}],
    "ops_extranjero": [{"operacion":"...","efectivos":"-.-","ubicacion":"...","repliegue":"..."}]
  },
  "trazabilidad": {}
}""",
        reglas="Incluye los relevos con su periodo.",
    ),
    Seccion(
        clave="operaciones_terreno",
        requerido="operaciones",
        titulo="OPERACIONES (GUARDIÁN SOBERANO, UNIDADES EN TERRENO, TRASLADOS Y DESPLIEGUE)",
        ejemplo_ruta="operaciones.unidades_terreno_kpi.unidades_en_terreno",
        esquema="""{
  "operaciones": {
    "guardian_soberano": [{"jaf":"...","fuerza":"-.-","planif":"-.-","ejecut":"-.-"}],
    "unidades_terreno_kpi": {"unidades_en_terreno":"-.-","fuerza_en_terreno":"-.-","lugares_activos":"-.-","actividad_principal":"..."},
    "traslados_uac": [{"uac":"...","unidades":"-.-"}],
    "unidades_terreno": [{"actividad":"...","comando_matriz":"...","ur":"...","fechas":"...","ubicacion":"...","fuerza":"-.-"}],
    "despliegue_mapa": {"mzn":"-.-","mzs":"-.-","antartica":"-.-"}
  },
  "trazabilidad": {}
}""",
        reglas=(
            "Guardián soberano con trabajos de tierra planificados/ejecutados; despliegue por macrozona "
            "MZN/MZS/Antártica. En \"traslados_uac\" usa el nombre corto de la UAC tal como aparezca en "
            "la fuente (p.ej. \"I DE\", \"COPE\", \"CAF\")."
        ),
    ),
    Seccion(
        clave="logistica",
        requerido="logistica",
        titulo="LOGÍSTICA",
        ejemplo_ruta="logistica.resumen.total",
        esquema="""{
  "logistica": {
    "resumen": {"total":"-.-","nop":"-.-"},
    "operacionalidad": [{"unidad":"...","total":"-.-","nop":"-.-","campana":"-.-","combate":"-.-","administrativos":"-.-","eq_ingenieros":"-.-"}]
  },
  "trazabilidad": {}
}""",
        reglas="Operacionalidad/NOP con sus categorías campaña, combate, administrativos y eq_ingenieros.",
    ),
)


def prompt(seccion: Seccion) -> str:
    texto = _CABECERA.format(titulo=seccion.titulo, esquema=seccion.esquema)
    texto += _REGLAS_COMUNES.format(ejemplo=seccion.ejemplo_ruta)
    if seccion.reglas:
        texto += "\n" + seccion.reglas
    return texto


def _unir(destino: dict[str, Any], parcial: dict[str, Any]) -> None:
    """Une el JSON de una sección al briefing (los dicts se mezclan, p.ej. 'operaciones')."""
    for k, v in parcial.items():
        if k == "trazabilidad":
            if isinstance(v, dict):
                for ruta, ids in v.items():
                    if isinstance(ids, list):
                        destino.setdefault("trazabilidad", {}).setdefault(str(ruta), []).extend(
                            str(i) for i in ids
                        )
            continue
        if isinstance(v, dict) and isinstance(destino.get(k), dict):
            destino[k].update(v)
        else:
            destino[k] = v


class SeccionIncompleta(ValueError):
    """La respuesta es JSON válido pero no trae la parte que se pidió."""


def _exigir(sec: Seccion, parcial: dict[str, Any]) -> None:
    valor = parcial.get(sec.requerido)
    if sec.requerido == "resumen_ejecutivo":
        if not isinstance(valor, list) or not any(str(x).strip() for x in valor):
            raise SeccionIncompleta("el modelo no devolvió el resumen ejecutivo")
    elif not isinstance(valor, dict):
        raise SeccionIncompleta(f"el modelo no devolvió '{sec.requerido}'")


def sintetizar(
    chat_json: Callable[..., dict[str, Any]],
    hechos: list[dict[str, Any]],
    parametros: dict[str, Any],
    *,
    secciones: tuple[Seccion, ...] = SECCIONES,
    al_avanzar: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Redacta el briefing sección por sección.

    `chat_json(system, user, operacion=...)` es la llamada del proveedor (con sus
    reintentos). Devuelve (briefing_unido_sin_validar, avisos).
    Propaga la excepción si falla una sección obligatoria.
    """
    payload = json.dumps({"hechos": hechos, "parametros": parametros}, ensure_ascii=False)
    briefing: dict[str, Any] = {"trazabilidad": {}}
    avisos: list[str] = []
    for i, sec in enumerate(secciones):
        if al_avanzar:
            al_avanzar(i, len(secciones), sec.titulo)
        try:
            parcial = chat_json(prompt(sec), payload, operacion=f"sintesis:{sec.clave}")
            _exigir(sec, parcial)
        except Exception as e:  # noqa: BLE001
            if sec.obligatoria:
                raise
            logger.warning("Sección %s sin completar: %s", sec.clave, e)
            avisos.append(
                f"La sección {sec.titulo} no se pudo redactar con este modelo y quedó vacía; "
                "revísela o regenere con un modelo de mayor capacidad."
            )
            continue
        _unir(briefing, parcial)
    return briefing, avisos
