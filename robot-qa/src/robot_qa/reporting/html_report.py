"""Reportero (Guia S4 paso 7, S5 'Report Engine'): HTML legible con evidencia por caso."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import CampaignResult

_TEMPLATES = Path(__file__).parent / "templates"


def _format_metrics(metrics: dict) -> dict[str, str]:
    out = {}
    for k, v in metrics.items():
        if isinstance(v, float):
            out[k] = f"{v:.3f}"
        else:
            out[k] = str(v)
    return out


def write_html_report(result: CampaignResult, out_path: Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.j2")
    html = template.render(result=result, metrics_display=_format_metrics(result.metrics))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
