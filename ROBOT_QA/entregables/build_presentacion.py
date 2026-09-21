"""Regenera ROBOT_QA/entregables/Presentacion_RobotQA.pptx desde los reportes
reales de robot-qa/reports/, con el mismo lenguaje visual que la versión
anterior (banda superior blanca, eyebrow + título Cambria, tarjetas con
borde claro, pie "Robot QA — MVP-Ciitec" + número de slide).

Uso:
    python ROBOT_QA/entregables/build_presentacion.py \
        --run smoke-20260921T174007Z --baseline smoke-20260920T180712Z
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from build_common import ASSETS_DIR, FONT_HEADING, FONT_BODY, FONT_MONO, PALETTE, case_rows, diff_runs, load_run

OUT_PATH = Path(__file__).resolve().parent / "Presentacion_RobotQA.pptx"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
BG_CONTENT = "F4F7FA"
BG_DIVIDER = PALETTE["navy_deep"]

def _rgb(hexstr: str) -> RGBColor:
    return RGBColor.from_string(hexstr)


def new_slide(prs: Presentation, bg: str):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(bg)
    return slide


def add_rect(slide, left, top, width, height, fill=None, line=None, line_w=None, shadow=False):
    from pptx.enum.shapes import MSO_SHAPE
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(fill)
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = _rgb(line)
        shape.line.width = line_w or Pt(0.75)
    shape.shadow.inherit = shadow
    return shape


def add_text(slide, left, top, width, height, text, *, size=12, color=PALETTE["ink"],
             bold=False, italic=False, font=FONT_BODY, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, line_spacing=1.0):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        r = p.add_run()
        r.text = line
        r.font.name = font
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.italic = italic
        r.font.color.rgb = _rgb(color)
    return box


def add_bullets(slide, left, top, width, height, items, *, size=12.5, color=PALETTE["ink"],
                 font=FONT_BODY, space_after=10, bullet_color=None):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_top = 0
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = f"—  {item}"
        r.font.name = font
        r.font.size = Pt(size)
        r.font.color.rgb = _rgb(color)
    return box


def add_footer(slide, page_num: int):
    add_text(slide, Inches(0.5), Inches(7.1), Inches(6.0), Inches(0.3),
              "Robot QA — MVP-Ciitec", size=9, color=PALETTE["muted"])
    add_text(slide, Inches(12.3), Inches(7.1), Inches(0.5), Inches(0.3),
              str(page_num), size=9, color=PALETTE["muted"])


def add_content_header(slide, eyebrow: str, title: str):
    add_rect(slide, Emu(0), Emu(0), SLIDE_W, Inches(1.05), fill=PALETTE["white"])
    add_text(slide, Inches(0.6), Inches(0.16), Inches(8.0), Inches(0.3),
              eyebrow.upper(), size=11, bold=True, color=PALETTE["teal"], font=FONT_BODY)
    add_text(slide, Inches(0.6), Inches(0.42), Inches(12.0), Inches(0.6),
              title, size=26, bold=True, color=PALETTE["ink"], font=FONT_HEADING)


def add_content_slide(prs, eyebrow, title, page_num):
    slide = new_slide(prs, BG_CONTENT)
    add_content_header(slide, eyebrow, title)
    add_footer(slide, page_num)
    return slide


def add_section_divider(prs, number: str, title: str, subtitle: str, page_num: int | None = None):
    slide = new_slide(prs, BG_DIVIDER)
    add_rect(slide, Emu(0), Emu(0), Inches(2.0), SLIDE_H, fill=PALETTE["navy"])
    add_text(slide, Inches(0.5), Inches(0.5), Inches(1.2), Inches(1.0), number,
              size=54, bold=True, color=PALETTE["teal"], font=FONT_HEADING)
    add_text(slide, Inches(2.5), Inches(2.9), Inches(10.0), Inches(1.3), title,
              size=40, bold=True, color=PALETTE["white"], font=FONT_HEADING)
    add_text(slide, Inches(2.5), Inches(4.0), Inches(9.5), Inches(0.8), subtitle,
              size=16, color=PALETTE["teal_light"], font=FONT_BODY)
    if page_num:
        add_footer(slide, page_num)
    return slide


def add_kpi_card(slide, left, top, width, height, value, label, accent):
    add_rect(slide, left, top, width, height, fill=PALETTE["white"])
    add_rect(slide, left, top, Inches(0.07), height, fill=accent)
    add_text(slide, left + Inches(0.25), top + Inches(0.12), width - Inches(0.4), Inches(1.0),
              value, size=34, bold=True, color=accent, font=FONT_HEADING)
    add_text(slide, left + Inches(0.25), top + Inches(1.15), width - Inches(0.4), Inches(0.45),
              label, size=11.5, color=PALETTE["muted"], font=FONT_BODY)


def add_gate_card(slide, left, top, width, height, gate_text, accent):
    add_rect(slide, left, top, width, height, fill=accent)
    add_text(slide, left + Inches(0.25), top + Inches(0.15), width - Inches(0.5), Inches(0.35),
              "GATE", size=11, bold=True, color=PALETTE["white"], font=FONT_BODY)
    add_text(slide, left + Inches(0.25), top + Inches(0.45), width - Inches(0.5), Inches(0.9),
              gate_text, size=26, bold=True, color=PALETTE["white"], font=FONT_HEADING)


def add_table(slide, left, top, width, height, headers, rows, *, col_widths=None,
              header_fill=PALETTE["navy"], row_alt=BG_CONTENT, cell_colors=None, font_size=13):
    n_rows = len(rows) + 1
    n_cols = len(headers)
    gfx = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    table = gfx.table
    if col_widths:
        total = sum(col_widths)
        for i, w in enumerate(col_widths):
            table.columns[i].width = Emu(int(width * (w / total)))

    for c, htext in enumerate(headers):
        cell = table.cell(0, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(header_fill)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = Inches(0.08)
        tf = cell.text_frame
        tf.text = htext
        run = tf.paragraphs[0].runs[0]
        run.font.name = FONT_BODY
        run.font.size = Pt(font_size)
        run.font.bold = True
        run.font.color.rgb = _rgb(PALETTE["white"])

    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row):
            cell = table.cell(r, c)
            fill = row_alt if r % 2 == 0 else PALETTE["white"]
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(fill)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = Inches(0.08)
            tf = cell.text_frame
            tf.text = str(val)
            run = tf.paragraphs[0].runs[0]
            run.font.name = FONT_BODY
            run.font.size = Pt(font_size)
            color = PALETTE["ink"]
            if cell_colors and (r - 1, c) in cell_colors:
                color = cell_colors[(r - 1, c)]
            run.font.color.rgb = _rgb(color)
    return gfx


def add_icon(slide, path, left, top, size):
    if path and Path(path).is_file():
        slide.shapes.add_picture(str(path), left, top, width=size, height=size)


def add_comparison_card(slide, left, top, width, height, icon, label, label_color, bullets, *, label_size=18):
    add_rect(slide, left, top, width, height, fill=PALETTE["white"])
    if icon:
        add_icon(slide, icon, left + Inches(0.35), top + Inches(0.25), Inches(0.5))
    add_text(slide, left + Inches(1.0), top + Inches(0.3), width - Inches(1.3), Inches(0.5),
              label, size=label_size, bold=True, color=label_color, font=FONT_HEADING)
    add_bullets(slide, left + Inches(0.35), top + Inches(1.0), width - Inches(0.7), height - Inches(1.3),
                bullets, size=13, space_after=10)


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def fmt_s(x) -> str:
    return "—" if x is None else f"{x:.1f}s"


# ======================================================================= build
def build(run_id: str, baseline_id: str) -> None:
    run = load_run(run_id)
    baseline = load_run(baseline_id)
    diff = diff_runs(run_id, baseline_id)
    rows = case_rows(run)
    rows_base = case_rows(baseline)
    m, mb = run["metrics"], baseline["metrics"]

    icons = sorted(ASSETS_DIR.glob("icon_*.png"))
    icon_logo = icons[0] if len(icons) > 0 else None
    icon_a = icons[2] if len(icons) > 2 else (icons[0] if icons else None)
    icon_b = icons[3] if len(icons) > 3 else (icons[0] if icons else None)

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    # ---------------------------------------------------------------- 1. Portada
    s = new_slide(prs, BG_DIVIDER)
    for i, (sz, off) in enumerate([(3.0, 0.3), (2.65, 1.2), (2.3, 2.1), (1.95, 3.0), (1.6, 3.9), (1.25, 4.8)]):
        add_rect(s, Inches(13.333 - sz - (0.02 * i)), Inches(off), Inches(sz), Inches(sz), fill=PALETTE["navy"])
    if icon_logo:
        add_icon(s, icon_logo, Inches(0.7), Inches(0.7), Inches(0.9))
    add_text(s, Inches(0.6), Inches(2.5), Inches(11.0), Inches(1.2), "ROBOT QA",
              size=44, bold=True, color=PALETTE["white"], font=FONT_HEADING)
    add_text(s, Inches(0.65), Inches(3.55), Inches(10.5), Inches(0.6),
              "Pruebas automatizadas para un sistema con Inteligencia Artificial",
              size=18, color=PALETTE["teal_light"], font=FONT_BODY)
    add_rect(s, Inches(0.65), Inches(4.35), Inches(3.5), Pt(2), fill=PALETTE["teal"])
    add_text(s, Inches(0.65), Inches(4.55), Inches(10.5), Inches(0.4),
              "Proyecto: Síntesis Automática de Reportes y Briefings Operacionales (MVP-Ciitec)",
              size=13, color=PALETTE["pale"], font=FONT_BODY)
    add_text(s, Inches(0.65), Inches(4.9), Inches(10.5), Inches(0.4),
              "Taller en Empresa 2  ·  Facultad de Ingeniería, Universidad San Sebastián",
              size=13, color=PALETTE["pale"], font=FONT_BODY)
    add_text(s, Inches(0.65), Inches(6.6), Inches(10.0), Inches(0.4),
              "Equipo: [completar]   ·   23 de septiembre de 2026",
              size=12, color=PALETTE["muted"], font=FONT_BODY)

    # ---------------------------------------------------------------- 2. Agenda
    s = add_content_slide(prs, "", "Agenda", 2)
    agenda = [
        ("01", "Análisis del problema", "Por qué probar un sistema con LLM es distinto"),
        ("02", "Diseño y desarrollo", "Arquitectura, catálogo de casos y gate de liberación"),
        ("03", "Resultados obtenidos", "Corrida real contra la API — del hallazgo a la corrección validada"),
        ("04", "Conclusiones y mejoras", "Qué funcionó, qué falta y el backlog"),
    ]
    y = 1.5
    for num, title, sub in agenda:
        add_text(s, Inches(0.7), Inches(y), Inches(1.1), Inches(1.1), num,
                  size=26, bold=True, color=PALETTE["teal"], font=FONT_HEADING)
        add_text(s, Inches(2.15), Inches(y + 0.05), Inches(9.5), Inches(0.5), title,
                  size=18, bold=True, color=PALETTE["ink"], font=FONT_HEADING)
        add_text(s, Inches(2.15), Inches(y + 0.52), Inches(9.5), Inches(0.5), sub,
                  size=12.5, color=PALETTE["muted"], font=FONT_BODY)
        y += 1.35

    # ---------------------------------------------------------------- 3. Divisor 01
    add_section_divider(prs, "01", "Análisis del problema",
                         "¿Qué cambia cuando el sistema bajo prueba tiene un LLM adentro?")

    # ---------------------------------------------------------------- 4. El sistema bajo prueba
    s = add_content_slide(prs, "Contexto", "El sistema bajo prueba", 4)
    add_text(s, Inches(0.95), Inches(1.6), Inches(6.2), Inches(0.5), "MVP-Ciitec",
              size=18, bold=True, color=PALETTE["navy"], font=FONT_HEADING)
    add_bullets(s, Inches(0.95), Inches(2.2), Inches(6.2), Inches(4.2), [
        "Ingiere documentos heterogéneos (PDF, Word, Excel, correo, bitácora)",
        "Extrae hechos operacionales con un LLM (Gemini 2.5 Flash)",
        "Sintetiza un briefing institucional versionado y trazable",
        "Detecta inconsistencias entre hechos de distintas fuentes",
        "Exporta a PDF / Word / texto / PPTX",
        "Control de acceso por rol, unidad y nivel de clasificación",
    ], size=13.5)
    add_rect(s, Inches(7.9), Inches(1.5), Pt(1.5), Inches(4.9), fill=PALETTE["rule"])
    if icon_a:
        add_icon(s, icon_a, Inches(8.15), Inches(1.65), Inches(0.55))
    add_text(s, Inches(8.85), Inches(1.72), Inches(3.7), Inches(0.5), "Por eso es distinto",
              size=15, bold=True, color=PALETTE["teal"], font=FONT_HEADING)
    add_bullets(s, Inches(8.15), Inches(2.45), Inches(4.3), Inches(4.2), [
        "Respuesta no determinista",
        "Coincidencia exacta no alcanza: hace falta evaluación semántica",
        "Dependiente del contexto (prompt, documentos, historial)",
        "Riesgo real de alucinación",
        "Superficie de ataque nueva: prompt injection, RAG contaminado",
        "Costo y latencia importan tanto como la calidad",
    ], size=12.5)

    # ---------------------------------------------------------------- 5. Riesgos priorizados
    s = add_content_slide(prs, "Análisis del problema", "Riesgos priorizados", 5)
    risks = [
        ("Fuga de datos por nivel de clasificación", "Crítica", PALETTE["red"]),
        ("Prompt injection vía documento cargado", "Crítica", PALETTE["red"]),
        ("Alucinación / cita sin respaldo real", "Alta", PALETTE["amber"]),
        ("Regresión no detectada entre versiones", "Alta", PALETTE["amber"]),
        ("Dependencia de disponibilidad del proveedor LLM", "Alta", PALETTE["amber"]),
        ("No determinismo entre repeticiones", "Media", PALETTE["teal"]),
    ]
    y = 1.45
    for text, sev, color in risks:
        add_rect(s, Inches(0.9), Inches(y), Inches(9.3), Inches(0.74), fill=PALETTE["white"])
        add_text(s, Inches(1.1), Inches(y + 0.2), Inches(8.9), Inches(0.4), text,
                  size=13.5, color=PALETTE["ink"])
        add_rect(s, Inches(10.5), Inches(y + 0.12), Inches(1.9), Inches(0.5), fill=color)
        add_text(s, Inches(10.5), Inches(y + 0.24), Inches(1.9), Inches(0.3), sev,
                  size=12, bold=True, color=PALETTE["white"], align=PP_ALIGN.CENTER)
        y += 0.86

    # ---------------------------------------------------------------- 6. Divisor 02
    add_section_divider(prs, "02", "Diseño y desarrollo",
                         "Arquitectura, catálogo de casos y gate de liberación")

    # ---------------------------------------------------------------- 7. Arquitectura
    s = add_content_slide(prs, "Diseño y desarrollo", "Arquitectura del robot", 7)
    stages = [
        ("Orquestador", "lee campaña y configuración"),
        ("Adaptador", "invoca la API real (REST)"),
        ("Capturador", "guarda evidencia reproducible"),
        ("Evaluadores", "9 evaluadores, 6 niveles"),
        ("Agregador", "gate de liberación"),
        ("Reportero", "HTML / JSON / JUnit"),
    ]
    x = 0.6
    for i, (title, sub) in enumerate(stages):
        add_rect(s, Inches(x), Inches(2.75), Inches(1.85), Inches(0.4), fill=PALETTE["navy"])
        add_text(s, Inches(x), Inches(2.8), Inches(1.85), Inches(0.35), title,
                  size=11.5, bold=True, color=PALETTE["white"], align=PP_ALIGN.CENTER)
        add_rect(s, Inches(x), Inches(3.18), Inches(1.85), Inches(0.85), fill=PALETTE["white"])
        add_text(s, Inches(x + 0.08), Inches(3.28), Inches(1.69), Inches(0.65), sub,
                  size=10.5, color=PALETTE["muted"], align=PP_ALIGN.CENTER)
        if i < len(stages) - 1:
            add_text(s, Inches(x + 1.87), Inches(2.9), Inches(0.23), Inches(0.5), "→",
                      size=16, color=PALETTE["teal"], align=PP_ALIGN.CENTER)
        x += 2.05
    add_text(s, Inches(0.6), Inches(4.5), Inches(12.0), Inches(0.4),
              "Guía ROBOT_QA §4 — el mismo flujo para las 6 familias de prueba",
              size=12, italic=True, color=PALETTE["muted"])
    add_rect(s, Inches(0.6), Inches(5.05), Inches(12.0), Inches(1.5), fill=PALETTE["white"])
    add_text(s, Inches(0.85), Inches(5.25), Inches(11.5), Inches(1.1), [
        "SutAdapter.invoke(caso) → Observation  ·  Evaluator.evaluate(caso, observación, contexto) → Score",
        "ReplayAdapter: reejecuta evaluadores sobre evidencia guardada, sin llamar de nuevo al SUT ni al LLM",
    ], size=12, font=FONT_MONO, color=PALETTE["navy"], line_spacing=1.5)

    # ---------------------------------------------------------------- 8. 6 niveles de evaluación
    s = add_content_slide(prs, "Diseño y desarrollo — Guía ROBOT_QA §7", "6 niveles de evaluación, 9 evaluadores", 8)
    levels = [
        ("1", "Aserciones deterministas", "schema · http_contract · rbac_leak · budget"),
        ("2", "Comparación con referencia", "required_fact"),
        ("3", "Métricas / relaciones metamórficas", "metamorphic"),
        ("4-5", "Rúbricas semánticas / juez LLM", "rubric_llm"),
        ("6", "Revisión humana + calibración", "human_review"),
    ]
    y = 1.5
    for num, title, evs in levels:
        add_rect(s, Inches(0.7), Inches(y), Inches(0.65), Inches(0.65), fill=PALETTE["teal"])
        add_text(s, Inches(0.7), Inches(y + 0.14), Inches(0.65), Inches(0.4), num,
                  size=14, bold=True, color=PALETTE["white"], align=PP_ALIGN.CENTER)
        add_text(s, Inches(1.6), Inches(y - 0.03), Inches(4.3), Inches(0.7), title,
                  size=14, bold=True, color=PALETTE["ink"])
        add_text(s, Inches(6.1), Inches(y - 0.03), Inches(6.6), Inches(0.7), evs,
                  size=13, font=FONT_MONO, color=PALETTE["navy"])
        y += 0.95

    # ---------------------------------------------------------------- 9. Catálogo de casos
    s = add_content_slide(prs, "Diseño y desarrollo", "Catálogo de casos: 52 en 6 familias", 9)
    cats = [("10", "Funcional"), ("12", "RAG"), ("10", "Robustez"),
            ("10", "Seguridad"), ("5", "Rendimiento"), ("5", "Confiabilidad")]
    x = 0.6
    for count, label in cats:
        add_rect(s, Inches(x), Inches(1.5), Inches(1.85), Inches(1.3), fill=PALETTE["white"])
        add_text(s, Inches(x), Inches(1.65), Inches(1.85), Inches(0.6), count,
                  size=26, bold=True, color=PALETTE["teal"], font=FONT_HEADING, align=PP_ALIGN.CENTER)
        add_text(s, Inches(x), Inches(2.35), Inches(1.85), Inches(0.4), label,
                  size=11.5, color=PALETTE["muted"], align=PP_ALIGN.CENTER)
        x += 2.0
    add_bullets(s, Inches(0.6), Inches(3.3), Inches(12.0), Inches(3.2), [
        "Formato de caso versionado en YAML (case_id, requirement_id, evaluators, thresholds, "
        "repetitions, severity)",
        "Trazable a los requisitos RF-001..010 / RNF-001..006 del README del proyecto",
        "Generado reproduciblemente por robot-qa/scripts/generate_testcases.py — el YAML "
        "resultante se versiona en git",
        "Criterio de aceptación de la Guía (≥ 50 casos, ≥ 4 familias, ≥ 5 evaluadores con ≥ 2 "
        "deterministas): superado",
    ], size=13)

    # ---------------------------------------------------------------- 10. Gate de liberación
    s = add_content_slide(prs, "Diseño y desarrollo — Guía ROBOT_QA §11", "Gate de liberación", 10)
    add_rect(s, Inches(0.6), Inches(1.5), Inches(5.8), Inches(3.0), fill=PALETTE["navy_deep"])
    code = (
        "si fallos_criticos > 0:\n"
        "    RECHAZAR\n"
        "si task_success_rate < umbral:\n"
        "    RECHAZAR\n"
        "si cola_revision > permitida:\n"
        "    REVISION HUMANA\n"
        "si no:\n"
        "    APROBAR"
    )
    add_text(s, Inches(0.85), Inches(1.7), Inches(5.3), Inches(2.6), code.split("\n"),
              size=13.5, font=FONT_MONO, color=PALETTE["teal_light"], line_spacing=1.3)
    add_bullets(s, Inches(6.8), Inches(1.6), Inches(5.9), Inches(3.2), [
        "PASS: se libera la versión",
        "HUMAN_REVIEW: casos límite van a una persona antes de decidir",
        "REJECT: hay evidencia suficiente para bloquear la liberación",
        "Cada corrida guarda un manifiesto: commit del SUT, commit del robot, modelo de LLM, umbrales",
    ], size=13)

    # ---------------------------------------------------------------- 11. Divisor 03
    add_section_divider(prs, "03", "Resultados obtenidos",
                         "Corrida real contra la API — sin datos inventados")

    # ---------------------------------------------------------------- 12. Resultados de la corrida
    s = add_content_slide(prs, "Resultados obtenidos", 'Resultados de la corrida "smoke"', 12)
    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
    kpis = [(str(len(rows)), "casos ejecutados", PALETTE["navy"]),
            (str(n_pass), "aprobados", PALETTE["green"]),
            (str(n_fail), "fallidos", PALETTE["green"] if n_fail == 0 else PALETTE["red"])]
    x = 0.6
    for value, label, color in kpis:
        add_kpi_card(s, Inches(x), Inches(1.5), Inches(2.7), Inches(1.7), value, label, color)
        x += 2.85
    gate_color = PALETTE["green"] if run["gate"] == "PASS" else (PALETTE["amber"] if run["gate"] == "HUMAN_REVIEW" else PALETTE["red"])
    add_gate_card(s, Inches(9.15), Inches(1.5), Inches(3.55), Inches(1.7), run["gate"], gate_color)

    case_table_rows = [[r["case_id"], r["requirement_id"], r["verdict"]] for r in rows]
    cell_colors = {(i, 2): (PALETTE["green"] if r["verdict"] == "PASS" else PALETTE["red"])
                   for i, r in enumerate(rows)}
    add_table(s, Inches(0.6), Inches(3.5), Inches(12.1), Inches(3.3),
              ["case_id", "requisito", "veredicto"], case_table_rows,
              col_widths=[3.5, 3.0, 5.6], cell_colors=cell_colors, font_size=13)

    # ---------------------------------------------------------------- 13. NUEVO — Antes vs. ahora
    s = add_content_slide(prs, "Resultados obtenidos", "Antes vs. ahora: FUNC-004 validado", 13)
    func004_base = next(r for r in rows_base if r["case_id"] == "FUNC-004")
    func004_now = next(r for r in rows if r["case_id"] == "FUNC-004")

    add_comparison_card(
        s, Inches(0.6), Inches(1.45), Inches(5.3), Inches(4.6),
        icon_a, baseline_id, PALETTE["red"],
        [
            f"Gate: {baseline['gate']} — 1 fallo crítico: FUNC-004",
            f"task_success_rate: {fmt_pct(mb['task_success_rate'])}",
            f"FUNC-004: FAIL — budget {fmt_s(func004_base['latency_s'])} (umbral 180s)",
            f"latency_p95: {fmt_s(mb['latency_p95_s'])}",
        ],
        label_size=15,
    )
    add_comparison_card(
        s, Inches(7.433), Inches(1.45), Inches(5.3), Inches(4.6),
        icon_b, run_id, PALETTE["green"],
        [
            f"Gate: {run['gate']}",
            f"task_success_rate: {fmt_pct(m['task_success_rate'])}",
            f"FUNC-004: PASS — budget {fmt_s(func004_now['latency_s'])} (umbral 180s)",
            f"latency_p95: {fmt_s(m['latency_p95_s'])}",
        ],
        label_size=15,
    )
    delta_s = func004_base["latency_s"] - func004_now["latency_s"]
    delta_pct = delta_s / func004_base["latency_s"] * 100
    badge_w = Inches(1.3)
    badge_left = Inches(5.9) + (Inches(1.533) - badge_w) // 2
    add_rect(s, badge_left, Inches(3.25), badge_w, Inches(1.0), fill=PALETTE["teal"])
    add_text(s, badge_left, Inches(3.37), badge_w, Inches(0.4), f"−{delta_s:.1f}s",
              size=15, bold=True, color=PALETTE["white"], font=FONT_HEADING, align=PP_ALIGN.CENTER)
    add_text(s, badge_left, Inches(3.75), badge_w, Inches(0.4), f"(−{delta_pct:.1f}%)",
              size=11, color=PALETTE["white"], align=PP_ALIGN.CENTER)

    # ---------------------------------------------------------------- 14. El hallazgo, ciclo cerrado
    s = add_content_slide(prs, "Resultados obtenidos", "Un hallazgo real: detectado, corregido y validado", 14)
    add_bullets(s, Inches(0.7), Inches(1.5), Inches(12.0), Inches(4.8), [
        f"Corrida {baseline_id}: 9 de 10 casos pasaron; FUNC-004 superó el presupuesto de "
        f"latencia — {fmt_s(func004_base['latency_s'])} contra un umbral de 180 s.",
        "Login, ingesta, versionado, point-in-time, exportación (PDF/Word/texto) y aprobación de "
        "versión pasaron sin observaciones desde la primera corrida.",
        "Causa raíz: Gemini 2.5 Flash genera “thinking” interno antes del JSON final; el esquema "
        "de síntesis es grande y con 3 documentos se acerca o supera el umbral.",
        "Mitigación aplicada: se desactiva el thinking de Gemini (reasoning_effort=“none”) en "
        "GeminiProvider (backend/app/llm/provider.py).",
        f"Validado: corrida {run_id} confirma la mitigación — FUNC-004 pasa en "
        f"{fmt_s(func004_now['latency_s'])}, gate de la campaña PASS.",
    ], size=14.5, space_after=14)

    # ---------------------------------------------------------------- 15. Demo de regresión
    s = add_content_slide(prs, "Resultados obtenidos", "Demostración: una regresión detectada por el robot", 15)
    add_comparison_card(s, Inches(0.6), Inches(1.5), Inches(5.9), Inches(4.3), icon_a, "main", PALETTE["green"], [
        "sintesis.py guarda la trazabilidad bullet → hecho",
        "citation_support encuentra citas resueltas",
        "Gate: PASS",
    ])
    add_comparison_card(s, Inches(6.8), Inches(1.5), Inches(5.9), Inches(4.3), icon_b, "demo/regresion-qa", PALETTE["red"], [
        "Se deshabilita a propósito el guardado de trazabilidad (1 commit, reversible)",
        "citation_support: 0 citas resueltas en los casos RAG",
        "task_success_rate cae bajo el umbral",
        "Gate: REJECT",
    ])

    # ---------------------------------------------------------------- 16. Divisor 04
    add_section_divider(prs, "04", "Conclusiones y oportunidades de mejora",
                         "Qué funcionó, qué falta y el backlog")

    # ---------------------------------------------------------------- 17. Conclusiones
    s = add_content_slide(prs, "Conclusiones y oportunidades de mejora", "Conclusiones", 17)
    add_bullets(s, Inches(0.7), Inches(1.5), Inches(12.0), Inches(4.8), [
        "El robot ejecuta contra el sistema REAL (no contra mocks): login LDAP, RBAC, Celery, "
        "Postgres, MinIO",
        "Captura evidencia reproducible: cada corrida queda con su manifiesto (commit, modelo, "
        "umbrales)",
        "Combina evaluación determinista, metamórfica y semántica en un solo gate de liberación",
        "Detecta tanto éxitos genuinos como fallas reales del sistema y de su proveedor de LLM",
        "Cerró el ciclo completo en esta iteración: detectó la falla, guió la corrección y validó "
        "el arreglo con una nueva corrida",
        "Puede reejecutar evaluadores sin volver a llamar al SUT ni al LLM (modo --replay)",
    ], size=14, space_after=12)

    # ---------------------------------------------------------------- 18. Backlog
    s = add_content_slide(prs, "Backlog", "Oportunidades de mejora", 18)
    add_bullets(s, Inches(0.7), Inches(1.5), Inches(12.0), Inches(4.8), [
        "Ejecutar la campaña completa (52 casos × 3 repeticiones) y fijar la línea base oficial",
        "Sumar un sexto usuario demo de otra unidad para cerrar la prueba de fuga entre unidades",
        "Instrumentar el backend para exponer tokens/costo por generación (cost_per_successful_task)",
        "Correr robot_qa calibrate con revisión humana real y reportar el acuerdo con el juez LLM",
        "Integrar la campaña smoke al pipeline de CI en cada pull request",
    ], size=14.5, space_after=14)

    # ---------------------------------------------------------------- 19. Gracias
    s = new_slide(prs, BG_DIVIDER)
    if icon_logo:
        add_icon(s, icon_logo, Inches(6.15), Inches(2.0), Inches(1.0))
    add_text(s, Inches(0.0), Inches(3.3), Inches(13.333), Inches(1.0), "Gracias",
              size=40, bold=True, color=PALETTE["white"], font=FONT_HEADING, align=PP_ALIGN.CENTER)
    add_text(s, Inches(0.0), Inches(4.2), Inches(13.333), Inches(0.6), "Preguntas y demo en vivo",
              size=16, color=PALETTE["teal_light"], align=PP_ALIGN.CENTER)

    prs.save(str(OUT_PATH))
    print(f"Presentación generada: {OUT_PATH} ({len(prs.slides._sldIdLst)} slides)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    build(args.run, args.baseline)
