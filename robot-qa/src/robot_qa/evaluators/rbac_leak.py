"""Evaluador determinista de seguridad (Guia S9): fuga entre unidades / niveles.

Usado con la accion `rbac_check` del adaptador: un usuario "prober" intenta
acceder a un recurso creado por "owner" de otra unidad o nivel. `case.expected
["expect_status"]` fija el codigo que el SUT DEBE devolver (403/404). Marcado
como `critical`: una fuga de datos entre unidades es un fallo critico que
fuerza REJECT en el gate (Guia S11), sin importar el resto de metricas.
"""
from __future__ import annotations

from ..models import Observation, Score, TestCase
from .base import EvaluatorContext


class RbacLeakEvaluator:
    id = "rbac_leak"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        if observation.error:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, critical=True, detail=f"error de transporte: {observation.error}",
            )
        expected_status = case.expected.get("expect_status", 403)
        got = observation.output.get("probed_status", observation.http_status)
        # Cualquier codigo de "denegado" cuenta como correcto si el caso acepta un rango.
        allowed = case.expected.get("expect_status_in", [expected_status])
        passed = got in allowed
        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=1.0 if passed else 0.0, passed=passed, critical=True,
            detail=f"status={got} (esperado en {allowed})",
        )
