"""Evaluador determinista de nivel 1 (Guia S7): codigos y campos obligatorios.

Assertions genericas de contrato HTTP, reusado por las acciones `login`,
`audit_check`, `export_check` y `approve_check` del adaptador:
  - `expected.expect_status`: codigo HTTP exacto esperado.
  - `expected.contains`: subcadenas que deben aparecer en la salida serializada.
  - `expected.not_contains`: subcadenas que NO deben aparecer (p.ej. secretos,
    API keys, el prompt de sistema) -- pruebas de divulgacion de datos (Guia S9).
"""
from __future__ import annotations

import json

from ..models import Observation, Score, TestCase
from .base import EvaluatorContext


class HttpContractEvaluator:
    id = "http_contract"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        problems: list[str] = []
        if observation.error:
            problems.append(f"error de transporte: {observation.error}")

        expected_status = case.expected.get("expect_status")
        if expected_status is not None and observation.http_status != expected_status:
            problems.append(f"status={observation.http_status} (esperado {expected_status})")

        blob = json.dumps(observation.output, ensure_ascii=False, default=str)
        for needle in case.expected.get("contains", []):
            if needle not in blob:
                problems.append(f"falta subcadena requerida: {needle!r}")
        for needle in case.expected.get("not_contains", []):
            if needle in blob:
                problems.append(f"aparece subcadena prohibida: {needle!r}")

        passed = not problems
        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=1.0 if passed else 0.0, passed=passed,
            critical=case.severity in ("high", "critical"),
            detail="; ".join(problems) if problems else "contrato HTTP cumplido",
        )
