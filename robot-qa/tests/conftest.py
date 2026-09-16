"""Fixtures compartidas: construyen TestCase/Observation/Score sin red ni LLM."""
from __future__ import annotations

import pytest

from robot_qa.evaluators.base import EvaluatorContext
from robot_qa.models import Observation, TestCase


def make_case(**overrides) -> TestCase:
    base = dict(case_id="TC-000", requirement_id="RF-000", category="funcional")
    base.update(overrides)
    return TestCase.model_validate(base)


def make_observation(**overrides) -> Observation:
    base = dict(case_id="TC-000", repetition=0, run_id="test-run")
    base.update(overrides)
    return Observation.model_validate(base)


def make_context(**overrides) -> EvaluatorContext:
    base = dict(run_id="test-run")
    base.update(overrides)
    return EvaluatorContext(**base)


@pytest.fixture
def briefing_out_minimo() -> dict:
    """Un `contenido` valido contra sut_contracts.BriefingOut, con lo minimo."""
    return {
        "resumen_ejecutivo": ["La unidad X ejecuto una actividad en Y."],
        "asuntos_criticos": [],
        "proyeccion_24_72h": "",
        "situacion": {}, "personal": {}, "inteligencia": {}, "operaciones": {}, "logistica": {},
        "trazabilidad": {},
    }
