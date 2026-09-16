"""Salida JUnit XML para el CI Connector (Guia S4/S5): exit code + artefacto legible por CI."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import CampaignResult, Verdict


def write_junit_report(result: CampaignResult, out_path: Path) -> Path:
    n = len(result.cases)
    failures = sum(1 for c in result.cases if c.verdict == Verdict.FAIL)
    errors = sum(1 for c in result.cases if c.verdict == Verdict.ERROR)
    skipped = sum(1 for c in result.cases if c.verdict == Verdict.HUMAN_REVIEW)

    suite = ET.Element(
        "testsuite", name=result.campaign, tests=str(n),
        failures=str(failures), errors=str(errors), skipped=str(skipped),
        timestamp=result.started_at,
    )
    for cr in result.cases:
        tc = ET.SubElement(suite, "testcase", classname=cr.case.category, name=cr.case.case_id)
        detalle = "; ".join(f"{s.evaluator_id}:{s.detail}" for s in cr.scores if not s.passed)
        if cr.verdict == Verdict.FAIL:
            ET.SubElement(tc, "failure", message=detalle or "fallo sin detalle").text = detalle
        elif cr.verdict == Verdict.ERROR:
            ET.SubElement(tc, "error", message=detalle or "error de ejecucion").text = detalle
        elif cr.verdict == Verdict.HUMAN_REVIEW:
            ET.SubElement(tc, "skipped", message="enviado a revision humana")

    tree = ET.ElementTree(ET.Element("testsuites"))
    tree.getroot().append(suite)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path
