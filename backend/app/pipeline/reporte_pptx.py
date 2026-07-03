"""
Filtro de salida — REPORTE INSTITUCIONAL en PDF (RF-008).

Se RELLENA la plantilla .pptx de 6 páginas (``templates/reporte_template.pptx``) con
los datos del briefing (JSON ``contenido`` == ``BriefingOut``) y se convierte a PDF con
LibreOffice headless. NO se genera el .pptx desde cero: se abre la plantilla y se editan
sus shapes in-place.

Reglas (fijadas con el usuario):
  * Los shapes de la plantilla se llaman genéricamente ``object N``; se mapean por
    ``(slide_idx_0based, shape.name)`` con el dict BINDINGS de abajo.
  * Texto: se edita ``runs[0].text`` conservando el formato. Tablas: se rellenan desde
    la 1ª fila de datos (``start_row``), clonando la última fila (<a:tr>) si faltan.
  * Dato ausente en el JSON -> celda en blanco. NUNCA se inventa (los ejemplos horneados
    en la plantilla se limpian al no haber dato).
  * Los "gráficos" de la plantilla son formas dibujadas (freeform), no charts nativos:
    se regeneran con matplotlib (PNG transparente, dpi=200) y se insertan en las MISMAS
    coordenadas, eliminando la(s) forma(s) original(es). Sin datos -> se omite el gráfico.

Gráficos: (1) dona Pers. Variable vs Planta (slide 2), (2) barras de fuerza por macrozona
(slide 2), (3) barras Total vs NOP de operacionalidad logística por unidad (slide 6).
"""
from __future__ import annotations

import io
import os
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.enum.text import MSO_AUTO_SIZE  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from ..config import settings  # noqa: E402

_TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates", "reporte_template.pptx")

# Paleta institucional (idéntica a la de la plantilla).
NAVY = "#1F3864"
AZUL = "#2E75B6"
CELESTE = "#9DC3E6"
ROJO = "#C00000"

_MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


# ---------------------------------------------------------------------------
#  Helpers de datos / formato
# ---------------------------------------------------------------------------
def _get(obj: Any, path: str) -> Any:
    """Resuelve rutas tipo 'a.b[0].c' dentro del contenido."""
    cur = obj
    for part in path.split("."):
        m = re.match(r"^([^\[]+)(?:\[(\d+)\])?$", part)
        if not m:
            return None
        key, idx = m.group(1), m.group(2)
        cur = cur.get(key) if isinstance(cur, dict) else None
        if idx is not None:
            cur = cur[int(idx)] if isinstance(cur, list) and len(cur) > int(idx) else None
        if cur is None:
            return None
    return cur


def _clean(v: Any) -> str:
    """Valor legible o '' si es placeholder ('-.-', '- . -', vacío, guiones)."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s or set(s) <= {"-", " ", ".", "–", "—"}:
        return ""
    return s


def _num(v: Any) -> float | None:
    """'2.305'/'5.911'/'4.565 Mts'/50 -> float (separador de miles '.'); si no, None."""
    if v is None:
        return None
    s = str(v).strip().replace(".", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _miles(v: float | None) -> str:
    """43720 -> '43.720' (separador de miles institucional)."""
    if v is None:
        return ""
    return f"{int(round(v)):,}".replace(",", ".")


def _fecha_es(f: datetime) -> str:
    """05MAY2026 (día + mes ES abreviado + año), igual que el encabezado de la plantilla."""
    return f"{f.day:02d}{_MESES[f.month - 1]}{f.year}"


def _by_name(slide) -> dict[str, Any]:
    return {sh.name: sh for sh in slide.shapes}


def _v(contenido: dict, path: str) -> str:
    return _clean(_get(contenido, path))


# ---------------------------------------------------------------------------
#  Ajuste de tipografía (LibreOffice NO agranda los shapes con autoajuste ni
#  respeta "shrink text on overflow": si el texto no cabe al tamaño horneado,
#  lo PARTE y se sale del recuadro -> superposiciones. Por eso fijamos tamaños
#  explícitos que caben en el ancho fijo del shape y desactivamos el autoajuste.)
# ---------------------------------------------------------------------------
def _fit(tf, pt: float | None = None, wrap: bool = True) -> None:
    """Normaliza un text_frame: word_wrap, sin autoajuste y (si `pt`) tamaño en todos los runs."""
    tf.word_wrap = wrap
    try:
        tf.auto_size = MSO_AUTO_SIZE.NONE
    except Exception:
        pass
    if pt is not None:
        for p in tf.paragraphs:
            for r in p.runs:
                r.font.size = Pt(pt)


def _shape_fit(shape, pt: float | None = None, wrap: bool = True) -> None:
    if shape is not None and shape.has_text_frame:
        _fit(shape.text_frame, pt, wrap)


def _para_fit(tf, idx: int, pt: float) -> None:
    """Fija el tamaño de un párrafo concreto (para KPIs que mezclan rótulo pequeño + cifra grande)."""
    paras = tf.paragraphs
    if -len(paras) <= idx < len(paras):
        for r in paras[idx].runs:
            r.font.size = Pt(pt)


def _cell_fit(shape, sizes: dict[tuple[int, int], float], wrap: bool = False) -> None:
    """Reajusta el tamaño de celdas concretas (p.ej. títulos de banda horneados en la tabla)."""
    tbl = shape.table
    for (r, c), pt in sizes.items():
        _fit(tbl.cell(r, c).text_frame, pt, wrap)


def _move(shape, left=None, top=None, width=None, height=None) -> None:
    if left is not None:
        shape.left = left
    if top is not None:
        shape.top = top
    if width is not None:
        shape.width = width
    if height is not None:
        shape.height = height


# ---------------------------------------------------------------------------
#  Edición de texto / tablas conservando formato
# ---------------------------------------------------------------------------
def _set_para(tf, idx: int, text: str) -> None:
    """Edita el párrafo `idx`: fija runs[0].text y elimina runs sobrantes (conserva formato)."""
    paras = tf.paragraphs
    if idx < 0:
        idx += len(paras)
    if not (0 <= idx < len(paras)):
        return
    p = paras[idx]
    if p.runs:
        p.runs[0].text = text
        for r in p.runs[1:]:
            r._r.getparent().remove(r._r)
    else:
        p.add_run().text = text


def _set_text(tf, text: str) -> None:
    """Colapsa el text_frame a un solo párrafo/run con `text`, conservando el formato del 1º."""
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    _set_para(tf, 0, text)


def _append_line(tf, text: str) -> None:
    """Añade una línea nueva clonando el formato del último párrafo (para captions KPI)."""
    if not text:
        return
    last = tf.paragraphs[-1]._p
    new = deepcopy(last)
    last.getparent().append(new)
    _set_para(tf, len(tf.paragraphs) - 1, text)


def _set_cell(cell, text: str, size: float | None = None) -> None:
    _set_text(cell.text_frame, text)
    if size is not None:
        _fit(cell.text_frame, size, wrap=True)


def _clone_rows(tbl, at_index: int, count: int) -> None:
    """Clona la fila <a:tr> `at_index` `count` veces, insertándola a continuación."""
    from pptx.oxml.ns import qn

    trs = tbl._tbl.findall(qn("a:tr"))
    src = trs[at_index]
    for _ in range(count):
        src.addnext(deepcopy(src))


def _fill_table_list(shape, items: list[dict], start_row: int, cols: dict[int, str],
                     footer: int = 0, can_clone: bool = True, size: float | None = None) -> None:
    """Rellena una tabla repetitiva desde `start_row`. Limpia filas de ejemplo sobrantes.

    `cols`: {índice_columna: campo_json}. `footer`: nº de filas finales intocables (p.ej. TOTAL).
    `size`: tamaño de fuente (pt) aplicado a las celdas de datos; imprescindible porque las
    celdas de ejemplo vienen vacías (sin run) y el run nuevo heredaría el default gigante (~18pt).
    """
    tbl = shape.table
    items = [it for it in (items or []) if isinstance(it, dict)]
    n = len(items)
    end = len(tbl.rows) - footer          # fin (exclusivo) de la zona de datos
    avail = end - start_row
    if n > avail and can_clone and avail >= 1:
        _clone_rows(tbl, at_index=end - 1, count=n - avail)
        end += n - avail
    for i in range(min(n, end - start_row)):
        for c, field in cols.items():
            _set_cell(tbl.cell(start_row + i, c), _clean(items[i].get(field)), size)
    # Limpia las filas de ejemplo que quedaron sin dato (evita mostrar cifras horneadas).
    for r in range(start_row + n, end):
        for c in cols:
            _set_cell(tbl.cell(r, c), "")


def _fill_cells(shape, cellmap: dict[tuple[int, int], str], size: float | None = None) -> None:
    tbl = shape.table
    for (r, c), val in cellmap.items():
        _set_cell(tbl.cell(r, c), val, size)


def _fill_labelvalue(shape, cellmap: dict[tuple[int, int], str], size: float | None = None) -> None:
    """Celdas 'ETIQUETA: valor': conserva la etiqueta del template y le anexa el valor."""
    tbl = shape.table
    for (r, c), val in cellmap.items():
        cell = tbl.cell(r, c)
        label = cell.text.strip()
        _set_cell(cell, f"{label} {val}".strip() if val else label, size)


def _clear_cells(shape, coords: list[tuple[int, int]]) -> None:
    tbl = shape.table
    for r, c in coords:
        _set_cell(tbl.cell(r, c), "")


# ---------------------------------------------------------------------------
#  Gráficos (matplotlib -> PNG transparente)
# ---------------------------------------------------------------------------
def _fig_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return buf.getvalue()


def _chart_donut(pf: dict) -> bytes | None:
    """Dona Pers. Variable (SLTP+SLC) vs Planta (resto). Centro = total."""
    planta = sum(x for k in ("OF", "SOF", "ECP", "ESCMIL", "ESCSOF", "ESCSERV", "personal_civil")
                 if (x := _num(pf.get(k))))
    variable = sum(x for k in ("SLTP", "SLC") if (x := _num(pf.get(k))))
    if planta + variable <= 0:
        return None
    total = _num(pf.get("total")) or (planta + variable)
    fig, ax = plt.subplots(figsize=(3.0, 3.0))
    ax.pie(
        [planta, variable],
        labels=[f"Planta\n{_miles(planta)}", f"Variable\n{_miles(variable)}"],
        colors=[NAVY, CELESTE],
        startangle=90,
        wedgeprops={"width": 0.42, "edgecolor": "white"},
        textprops={"fontsize": 8, "color": "#333"},
    )
    ax.text(0, 0.05, _miles(total), ha="center", va="center", fontsize=14, fontweight="bold", color=NAVY)
    ax.text(0, -0.20, "TOTAL", ha="center", va="center", fontsize=8, color="#555")
    ax.set(aspect="equal")
    return _fig_png(fig)


def _chart_macrozonas(macrozonas: list[dict]) -> bytes | None:
    """Barras horizontales de fuerza por macrozona."""
    pares = [(m.get("zona", ""), _num(m.get("fuerza"))) for m in (macrozonas or []) if isinstance(m, dict)]
    pares = [(z, v) for z, v in pares if z and v]
    if not pares:
        return None
    fig, ax = plt.subplots(figsize=(5.6, 2.9))  # apaisado: encaja en el hueco entre bandas de sección
    zs = [z for z, _ in pares]
    vs = [v for _, v in pares]
    barras = ax.barh(zs, vs, color=NAVY)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vs) * 1.18)
    ax.bar_label(barras, labels=[_miles(v) for v in vs], padding=3, fontsize=8, color="#333")
    ax.tick_params(labelsize=8)
    ax.set_title("Parte de fuerza por macrozona", fontsize=10, color=NAVY, fontweight="bold")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _fig_png(fig)


def _chart_operacionalidad(items: list[dict], resumen: dict) -> bytes | None:
    """Barras agrupadas Total vs NOP (no operativos) por unidad."""
    filas = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        u = _clean(it.get("unidad"))
        t, n = _num(it.get("total")), _num(it.get("nop"))
        if u and (t or n):
            filas.append((u, t or 0, n or 0))
    if not filas:
        return None
    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    x = np.arange(len(filas))
    w = 0.4
    ax.bar(x - w / 2, [f[1] for f in filas], w, label="Total", color=NAVY)
    ax.bar(x + w / 2, [f[2] for f in filas], w, label="NOP", color=ROJO)
    ax.set_xticks(x)
    ax.set_xticklabels([f[0] for f in filas], rotation=35, ha="right", fontsize=8)
    ax.legend(fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    titulo = "Operacionalidad logística por unidad"
    tot, nop = _clean((resumen or {}).get("total")), _clean((resumen or {}).get("nop"))
    if tot or nop:
        titulo += f"   (Total {tot or '-'} / NOP {nop or '-'})"
    ax.set_title(titulo, fontsize=11, color=NAVY, fontweight="bold")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return _fig_png(fig)


def _reemplazar(slide, names: list[str], png: bytes | None, rect=None) -> None:
    """Elimina los shapes `names` (formas nativas del gráfico) e inserta `png` en su
    bounding box (o en `rect`). Si `png` es None, solo elimina: el gráfico se OMITE por
    completo (no se deja la forma de ejemplo del template con su escala horneada)."""
    objetivo = set(names)
    shapes = [sh for sh in slide.shapes if sh.name in objetivo]
    if not shapes and rect is None:
        return
    if rect is None:
        left = min(s.left for s in shapes)
        top = min(s.top for s in shapes)
        width = max(s.left + s.width for s in shapes) - left
        height = max(s.top + s.height for s in shapes) - top
        rect = (left, top, width, height)
    for s in shapes:
        s._element.getparent().remove(s._element)
    if png is not None:
        slide.shapes.add_picture(io.BytesIO(png), *rect)


# Furniture de la barra de macrozonas (grupo + ejes/labels/ticks freeform) en slide idx1.
_MACRO_NAMES = ["object 28"] + [f"object {i}" for i in range(41, 67)]


# ---------------------------------------------------------------------------
#  Relleno de las 6 páginas (BINDINGS)
# ---------------------------------------------------------------------------
def _rellenar(slides, c: dict, fecha: datetime) -> None:
    fstr = _fecha_es(fecha)
    pf = "personal.parte_fuerza_institucional"

    # ---- Slide idx0: PORTADA (dashboard agregado) ----
    s0 = _by_name(slides[0])
    _fill_cells(s0["object 34"], {  # FUERZA SLC
        (1, 1): _v(c, "personal.slc.clase_2006"),
        (2, 1): _v(c, "personal.slc.clase_2007"),
        (3, 1): _v(c, "personal.slc.total"),
    }, size=9)
    _fill_cells(s0["object 39"], {  # total institucional (celda TOTAL)
        (3, 0): _v(c, f"{pf}.total"),
        (4, 0): _v(c, f"{pf}.total"),
    }, size=9)
    _fill_table_list(s0["object 10"], _get(c, "operaciones.guardian_soberano"),
                     start_row=2, cols={0: "jaf", 1: "fuerza", 2: "planif", 3: "ejecut"}, size=7)
    _fill_table_list(s0["object 8"], _get(c, "operaciones.ops_extranjero"),
                     start_row=1, cols={0: "operacion", 1: "efectivos"}, footer=1, can_clone=False, size=8)
    _fill_table_list(s0["object 5"], _get(c, "operaciones.unidades_terreno"), start_row=1,
                     cols={0: "comando_matriz", 1: "ur", 2: "fechas", 3: "ubicacion", 4: "fuerza"},
                     footer=1, can_clone=False, size=8)
    _fill_table_list(s0["object 40"], _get(c, "inteligencia.incidentes_mootw"),
                     start_row=1, cols={0: "unidad", 1: "tipo"}, can_clone=False, size=10)
    # Títulos-sección verdes (18pt con autoajuste -> parten en 2 líneas y pisan las tablas).
    for t in ("object 2", "object 4", "object 6", "object 9", "object 11", "object 12"):
        _shape_fit(s0[t], pt=11, wrap=False)
    # Cajas sin fuente limpia en el JSON -> en blanco (nunca inventar).
    _clear_cells(s0["object 3"], [(1, 0), (1, 1), (1, 2)])   # UFEC/BRIFE/PARME
    _clear_cells(s0["object 7"], [(1, 1), (3, 1)])            # Relevos (valores de ejemplo)
    for badge in ("object 24", "object 32", "object 25"):    # badges de mapa MZN/MZS/ANTÁRTICA ('xxx')
        _set_para(s0[badge].text_frame, 1, "")

    # ---- Slide idx1: PERSONAL ----
    s1 = _by_name(slides[1])
    _fill_labelvalue(s1["object 2"], {
        (0, 0): _v(c, f"{pf}.OF"), (1, 0): _v(c, f"{pf}.SOF"),
        (2, 0): _v(c, f"{pf}.ECP"), (3, 0): _v(c, f"{pf}.SLTP"),
        (0, 1): _v(c, f"{pf}.ESCMIL"), (1, 1): _v(c, f"{pf}.ESCSOF"),
        (2, 1): _v(c, f"{pf}.ESCSERV"), (3, 1): _v(c, f"{pf}.personal_civil"),
        (4, 1): _v(c, f"{pf}.SLC"),
    }, size=12)
    _fill_cells(s1["object 25"], {  # PARTE DE FUERZA DE CATÁSTROFE
        (1, 0): _v(c, "personal.catastrofe.fuerza"),
        (1, 1): _v(c, "personal.catastrofe.forman"),
        (1, 2): _v(c, "personal.catastrofe.faltan"),
    }, size=15)
    _set_text(s1["object 20"].text_frame, str(fecha.year))
    # Bandas de sección "N PARTE DE FUERZA ..." (título horneado a 20pt -> se sale del recuadro).
    for band in ("object 12", "object 13", "object 24"):
        _cell_fit(s1[band], {(0, 1): 14})

    # ---- Slide idx2: INTELIGENCIA ----
    s2 = _by_name(slides[2])
    _shape_fit(s2["object 8"], pt=11, wrap=True)   # título "SITUACIÓN DE INCIDENTES INSTITUCIONALES"
    _fill_table_list(s2["object 9"], _get(c, "inteligencia.incidentes_institucionales"),
                     start_row=1, cols={0: "tipo", 1: "descripcion"}, size=10)
    _fill_table_list(s2["object 21"], _get(c, "inteligencia.incidentes_mootw"),
                     start_row=2, cols={0: "tipo", 2: "unidad", 3: "descripcion"}, size=10)
    alertas = _get(c, "inteligencia.sistema_alerta") or []
    a0 = alertas[0] if len(alertas) > 0 and isinstance(alertas[0], dict) else {}
    a1 = alertas[1] if len(alertas) > 1 and isinstance(alertas[1], dict) else {}
    _fill_cells(s2["object 10"], {
        (2, 0): _clean(a0.get("alerta")), (2, 2): _clean(a0.get("area")),
        (2, 3): _clean(a0.get("unidad_asociada")), (2, 4): _clean(a0.get("apreciacion")),
        (3, 0): _clean(a1.get("alerta")), (3, 2): _clean(a1.get("area")),
        (3, 3): _clean(a1.get("unidad_asociada")), (3, 4): _clean(a1.get("apreciacion")),
        (5, 0): _v(c, "inteligencia.analisis_meteo"),
        (8, 0): _v(c, "inteligencia.proyeccion_meteo_48h"),
    }, size=9)
    _set_text(s2["object 17"].text_frame, fstr)

    # ---- Slide idx3: OPERACIONES (tablas) ----
    s3 = _by_name(slides[3])
    _fill_table_list(s3["object 15"], _get(c, "operaciones.ops_catastrofe"), start_row=2,
                     cols={0: "cantidad", 2: "tipo", 3: "unidad_origen", 4: "zona_empleo", 5: "inicio_empleo"},
                     size=9)
    _fill_table_list(s3["object 13"], _get(c, "operaciones.relevos_norte"),
                     start_row=2, cols={0: "n", 1: "fecha", 2: "jaf", 3: "unidades"}, size=10)
    _fill_table_list(s3["object 14"], _get(c, "operaciones.relevos_sur"),
                     start_row=2, cols={0: "n", 1: "fecha", 2: "ft", 3: "unidades"}, size=10)
    _fill_table_list(s3["object 12"], _get(c, "operaciones.ops_antartica"),
                     start_row=2, cols={0: "bae", 1: "dotacion_estival", 2: "cpccgu"}, size=10)
    _fill_table_list(s3["object 16"], _get(c, "operaciones.ops_extranjero"),
                     start_row=2, cols={0: "operacion", 1: "efectivos", 2: "ubicacion", 3: "repliegue"}, size=9)
    # Títulos de banda "N. TÍTULO" horneados a 18pt -> se salían y pisaban las tablas de abajo.
    for band, pt in (("object 15", 12), ("object 13", 12), ("object 14", 12),
                     ("object 12", 13), ("object 16", 13)):
        _cell_fit(s3[band], {(0, 1): pt})
    _set_text(s3["object 8"].text_frame, fstr)

    # ---- Slide idx4: OPERACIONES (KPIs + unidades en terreno) ----
    s4 = _by_name(slides[4])
    kpi = "operaciones.unidades_terreno_kpi"
    _set_para(s4["object 23"].text_frame, 1, _v(c, f"{kpi}.fuerza_en_terreno"))   # 'Fuerza en terreno' / valor
    _set_para(s4["object 39"].text_frame, 2, _v(c, f"{kpi}.unidades_en_terreno"))  # 'Unidades en'/'terreno'/valor
    _set_para(s4["object 46"].text_frame, 1, _v(c, f"{kpi}.lugares_activos"))       # 'Lugares activos' / valor
    _append_line(s4["object 51"].text_frame, _v(c, f"{kpi}.actividad_principal"))   # 'Actividad principal' + valor
    # KPIs: la cifra venía a 23-28pt y el rótulo se salía del recuadro. Rótulo pequeño + cifra media,
    # con word_wrap para que el texto quede dentro de cada tarjeta (1" de alto).
    for name, lbl, val, val_para in (("object 39", 10, 20, 2), ("object 23", 10, 18, 1),
                                     ("object 46", 10, 20, 1)):
        tf = s4[name].text_frame
        _fit(tf, wrap=True)
        for pi in range(val_para):
            _para_fit(tf, pi, lbl)
        _para_fit(tf, val_para, val)
    # 'Actividad principal': recuadro diminuto (0.59") y frase larga -> se ensancha a lo ancho de la
    # tarjeta (sin pisar el icono a la derecha) y se reduce la tipografía para que la frase quepa dentro.
    act = s4["object 51"]
    _move(act, left=Inches(2.19), width=Inches(0.98))
    tf = act.text_frame
    _fit(tf, pt=8, wrap=True)
    _fill_table_list(s4["object 37"], _get(c, "operaciones.unidades_terreno"), start_row=2,
                     cols={0: "actividad", 1: "comando_matriz", 2: "ur", 3: "fechas", 4: "ubicacion", 5: "fuerza"},
                     size=10)
    _cell_fit(s4["object 37"], {(0, 2): 13})   # banda "7. UNIDADES EN TERRENO"
    _set_text(s4["object 33"].text_frame, fstr)

    # ---- Slide idx5: LOGÍSTICA (solo fecha; el resto es el gráfico inyectado) ----
    _set_text(_by_name(slides[5])["object 9"].text_frame, fstr)

    # ---- Cabeceras comunes (idx1..idx5): caja negra de sección, título blanco "SITUACIÓN..."
    # y la fecha. En LibreOffice los tamaños horneados (28pt/15.5pt) no caben y parten en 2 líneas
    # ("OPERACIO NES", "SITUACIÓN DE / INTELIGENCIA") o recortan la fecha ("01JUL202"). Se fijan
    # tamaños que caben en el ancho fijo de cada recuadro (una sola línea).
    #        slide: (caja negra, título blanco, fecha)
    cabeceras = {
        1: ("object 18", "object 19", "object 20"),
        2: ("object 15", "object 16", "object 17"),
        3: ("object 6", "object 7", "object 8"),
        4: ("object 31", "object 32", "object 33"),
        5: ("object 7", "object 8", "object 9"),
    }
    for idx, (negra, blanco, fchbox) in cabeceras.items():
        nm = _by_name(slides[idx])
        _shape_fit(nm.get(negra), pt=18, wrap=False)
        _shape_fit(nm.get(blanco), pt=20, wrap=False)
        _shape_fit(nm.get(fchbox), pt=12, wrap=False)


def _graficos(prs, slides, c: dict) -> None:
    # (1) Dona Variable vs Planta + (2) barras macrozona -> slide idx1. Se quitan SIEMPRE las
    # formas nativas (dona/barras dibujadas del template); se inserta el PNG solo si hay datos.
    donut = _chart_donut(_get(c, "personal.parte_fuerza_institucional") or {})
    _reemplazar(slides[1], ["object 3", "object 8", "object 10", "object 11"], donut)
    barras = _chart_macrozonas(_get(c, "personal.macrozonas") or [])
    # El bbox de _MACRO_NAMES abarca ejes/labels que llegan hasta el pie de la lámina; usarlo como
    # rectángulo de inserción hacía un gráfico gigante que pisaba la banda "3 PARTE DE FUERZA...".
    # Se ancla el gráfico en el hueco entre la banda de la sección 2 y la de la 3.
    nm1 = _by_name(slides[1])
    banda2, banda3 = nm1.get("object 13"), nm1.get("object 24")
    m_top = (banda2.top + banda2.height + Inches(0.15)) if banda2 else Inches(5.75)
    m_bot = (banda3.top - Inches(0.15)) if banda3 else Inches(8.15)
    m_left = Inches(3.45)
    m_rect = (m_left, m_top, prs.slide_width - Inches(0.25) - m_left, m_bot - m_top)
    _reemplazar(slides[1], _MACRO_NAMES, barras, rect=m_rect)

    # (3) Barras operacionalidad -> slide idx5, en el área interior del marco. Sin datos se
    # mantiene el placeholder del template ("Gráficos eliminados intencionalmente").
    oper = _chart_operacionalidad(_get(c, "logistica.operacionalidad") or [], _get(c, "logistica.resumen") or {})
    if oper:
        nm = _by_name(slides[5])
        lado, cab = nm.get("object 11"), nm.get("object 12")
        left = (lado.left + lado.width + Inches(0.15)) if lado else Inches(2.6)
        top = (cab.top + cab.height + Inches(0.25)) if cab else Inches(2.75)
        width = prs.slide_width - Inches(0.35) - left
        height = int(width * 5.0 / 7.5)  # conserva el aspecto apaisado del gráfico (7.5x5.0)
        _reemplazar(slides[5], ["object 13"], oper, rect=(left, top, width, height))


# ---------------------------------------------------------------------------
#  PPTX -> PDF (LibreOffice headless) — python-pptx no exporta PDF
# ---------------------------------------------------------------------------
def _pptx_a_pdf(data: bytes) -> bytes:
    import glob
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "reporte.pptx")
        with open(src, "wb") as fh:
            fh.write(data)
        env = {**os.environ, "HOME": tempfile.gettempdir()}
        try:
            subprocess.run(
                [settings.soffice_bin, "--headless", "--convert-to", "pdf", "--outdir", tmp, src],
                check=True, env=env, capture_output=True, timeout=180,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"LibreOffice ('{settings.soffice_bin}') no está instalado; se requiere para "
                "exportar el briefing a PDF (RF-008). Ajusta SOFFICE_BIN."
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                "LibreOffice falló al convertir a PDF: " + e.stderr.decode("utf-8", "ignore")[:500]
            ) from e
        pdfs = glob.glob(os.path.join(tmp, "*.pdf"))
        if not pdfs:
            raise RuntimeError("LibreOffice no generó el PDF esperado.")
        with open(pdfs[0], "rb") as fh:
            return fh.read()


def generar_pdf(contenido: dict[str, Any], titulo: str, fecha: datetime) -> bytes:
    """Rellena la plantilla institucional y devuelve el PDF final (RF-008)."""
    prs = Presentation(_TEMPLATE)
    slides = list(prs.slides)
    _rellenar(slides, contenido, fecha)
    _graficos(prs, slides, contenido)
    buf = io.BytesIO()
    prs.save(buf)
    return _pptx_a_pdf(buf.getvalue())
