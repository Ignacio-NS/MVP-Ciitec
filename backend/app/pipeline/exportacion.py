"""
Filtro de salida — EXPORTACIÓN (RF-008): briefing -> PDF / Word / texto plano.

- PDF (maestro): se RELLENA la plantilla institucional de 6 páginas (.pptx) con los datos
  del briefing y se convierte a PDF con LibreOffice headless. Ver `reporte_pptx.py`.
- Word: documento .docx generado con python-docx (mismo contenido por secciones).
- Texto: volcado estructurado.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from . import reporte_pptx


def render_pdf(contenido: dict[str, Any], titulo: str, fecha: datetime) -> bytes:
    """PDF institucional: plantilla .pptx de 6 páginas rellenada -> LibreOffice -> PDF."""
    return reporte_pptx.generar_pdf(contenido, titulo, fecha)


def _hojas(contenido: dict[str, Any]) -> list[dict[str, Any]]:
    return [h for h in (contenido.get("hojas_adicionales") or []) if isinstance(h, dict)]


def _img_bytes(objeto: str) -> bytes | None:
    if not objeto:
        return None
    try:
        from .. import storage
        return storage.get_bytes(objeto)
    except Exception:
        return None


def render_texto(contenido: dict[str, Any], titulo: str, fecha: datetime) -> bytes:
    L = [f"{titulo}  ({fecha.strftime('%d-%m-%Y')})", "=" * 60, "", "RESUMEN EJECUTIVO:"]
    for b in contenido.get("resumen_ejecutivo", []) or ["-.-"]:
        L.append(f"  • {b}")
    sit = contenido.get("situacion") or {}
    L += ["", "SITUACIÓN:", "  " + (sit.get("resumen") or "-.-")]
    for a in sit.get("aspectos", []) or []:
        L.append(f"  • {a}")
    L += ["", "ASUNTOS CRÍTICOS:"]
    for a in contenido.get("asuntos_criticos", []) or []:
        L.append(f"  - {a.get('asunto','-.-')} | {a.get('impacto','-.-')} | {a.get('responsable','-.-')}")
    L += ["", "PROYECCIÓN 24-72H:", "  " + (contenido.get("proyeccion_24_72h") or "-.-")]
    for h in _hojas(contenido):
        L += ["", f"{(h.get('seccion') or 'INFORMACIÓN ADICIONAL').upper()} — {(h.get('titulo') or '').upper()}"]
        for b in h.get("bloques") or []:
            if not isinstance(b, dict):
                continue
            if b.get("titulo"):
                L.append(f"  {b['titulo']}:")
            t = b.get("tipo")
            if t == "texto" and b.get("texto"):
                L.append("  " + str(b["texto"]))
            elif t == "vinetas":
                L += [f"  • {x}" for x in b.get("items") or [] if str(x).strip()]
            elif t == "tabla":
                L.append("  " + " | ".join(str(c) for c in b.get("columnas") or []))
                L += ["  " + " | ".join(str(c) for c in f) for f in b.get("filas") or [] if isinstance(f, list)]
            elif t == "kpis":
                L += [f"  {i.get('etiqueta', '')}: {i.get('valor', '')}" for i in b.get("items") or []
                      if isinstance(i, dict)]
            elif t == "grafico":
                L += [f"  {c}: {v}" for c, v in zip(b.get("categorias") or [], b.get("valores") or [])]
            elif t == "imagen":
                L.append(f"  [imagen] {b.get('pie') or ''}".rstrip())
    return "\n".join(L).encode("utf-8")


def render_word(contenido: dict[str, Any], titulo: str, fecha: datetime) -> bytes:
    import docx

    doc = docx.Document()
    doc.add_heading(titulo, level=0)
    doc.add_paragraph(fecha.strftime("%d-%m-%Y"))

    doc.add_heading("Resumen ejecutivo", level=1)
    for b in contenido.get("resumen_ejecutivo", []) or ["-.-"]:
        doc.add_paragraph(b, style="List Bullet")

    sit = contenido.get("situacion") or {}
    doc.add_heading("Situación", level=1)
    doc.add_paragraph(sit.get("resumen") or "-.-")
    for a in sit.get("aspectos", []) or []:
        doc.add_paragraph(a, style="List Bullet")

    doc.add_heading("Asuntos críticos", level=1)
    ac = contenido.get("asuntos_criticos", []) or []
    if ac:
        t = doc.add_table(rows=1, cols=3)
        t.style = "Light Grid Accent 1"
        hdr = t.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text = "Asunto", "Impacto", "Responsable"
        for a in ac:
            cel = t.add_row().cells
            cel[0].text = a.get("asunto", "-.-")
            cel[1].text = a.get("impacto", "-.-")
            cel[2].text = a.get("responsable", "-.-")

    doc.add_heading("Proyección 24-72h", level=1)
    doc.add_paragraph(contenido.get("proyeccion_24_72h") or "-.-")

    for h in _hojas(contenido):
        doc.add_heading(f"{h.get('seccion') or 'Información adicional'} — {h.get('titulo') or ''}".strip(" —"),
                        level=1)
        for b in h.get("bloques") or []:
            if not isinstance(b, dict):
                continue
            if b.get("titulo"):
                doc.add_heading(str(b["titulo"]), level=2)
            t = b.get("tipo")
            if t == "texto":
                for par in str(b.get("texto") or "").splitlines():
                    if par.strip():
                        doc.add_paragraph(par)
            elif t == "vinetas":
                for x in b.get("items") or []:
                    if str(x).strip():
                        doc.add_paragraph(str(x), style="List Bullet")
            elif t == "tabla":
                cols = [str(c) for c in b.get("columnas") or []]
                filas = [f for f in b.get("filas") or [] if isinstance(f, list)]
                n = len(cols) or (max(len(f) for f in filas) if filas else 0)
                if n:
                    tb = doc.add_table(rows=1, cols=n)
                    tb.style = "Light Grid Accent 1"
                    for i in range(n):
                        tb.rows[0].cells[i].text = cols[i] if i < len(cols) else ""
                    for f in filas:
                        cel = tb.add_row().cells
                        for i in range(n):
                            cel[i].text = str(f[i]) if i < len(f) else ""
            elif t == "kpis":
                for i in b.get("items") or []:
                    if isinstance(i, dict):
                        doc.add_paragraph(f"{i.get('etiqueta', '')}: {i.get('valor', '')}", style="List Bullet")
            elif t == "grafico":
                for c, v in zip(b.get("categorias") or [], b.get("valores") or []):
                    doc.add_paragraph(f"{c}: {v}", style="List Bullet")
            elif t == "imagen":
                data = _img_bytes(str(b.get("objeto") or ""))
                if data:
                    import docx.shared
                    doc.add_picture(io.BytesIO(data), width=docx.shared.Inches(5.5))
                    if b.get("pie"):
                        doc.add_paragraph(str(b["pie"]))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render(contenido: dict[str, Any], formato: str, titulo: str, fecha: datetime) -> tuple[bytes, str, str]:
    """Devuelve (bytes, content_type, extension) según el formato."""
    formato = formato.upper()
    if formato == "PDF":
        return render_pdf(contenido, titulo, fecha), "application/pdf", "pdf"
    if formato == "WORD":
        return (
            render_word(contenido, titulo, fecha),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        )
    return render_texto(contenido, titulo, fecha), "text/plain; charset=utf-8", "txt"
