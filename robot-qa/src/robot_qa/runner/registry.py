"""Carga del Test Registry (Guia S4/S5): casos YAML versionados + config de campana."""
from __future__ import annotations

from pathlib import Path

import yaml

from ..models import TestCase


def load_cases(testcases_dir: Path, suites: list[str]) -> list[TestCase]:
    """Carga todos los casos de las suites dadas (subcarpetas de testcases/).

    Cada archivo YAML puede contener un caso (dict con case_id) o una lista de
    casos bajo la clave 'cases'. Falla ruidosamente ante case_id duplicados:
    un catalogo de pruebas con ids repetidos rompe la trazabilidad (Guia S10).
    """
    cases: list[TestCase] = []
    seen: dict[str, str] = {}
    for suite in suites:
        suite_dir = testcases_dir / suite
        if not suite_dir.is_dir():
            raise FileNotFoundError(f"suite '{suite}' no existe en {testcases_dir}")
        for yml in sorted(suite_dir.glob("*.yaml")):
            data = yaml.safe_load(yml.read_text(encoding="utf-8"))
            raw_cases = data.get("cases", [data]) if isinstance(data, dict) else data
            for raw in raw_cases:
                raw = dict(raw)
                raw.setdefault("source_file", str(yml.relative_to(testcases_dir.parent)))
                case = TestCase.model_validate(raw)
                if case.case_id in seen:
                    raise ValueError(
                        f"case_id duplicado '{case.case_id}' en {yml} (ya definido en {seen[case.case_id]})"
                    )
                seen[case.case_id] = str(yml)
                cases.append(case)
    return cases


def load_campaign_config(campaigns_dir: Path, campaign_name: str) -> dict:
    path = campaigns_dir / f"{campaign_name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"campana '{campaign_name}' no existe: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
