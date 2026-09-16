"""Evaluador determinista de nivel 1 (Guia S7): groundedness / fidelidad de citas.

Para cada bullet trazado (`GET /briefings/{id}/trazabilidad`, RF-006) verifica
que el `hecho_id` referenciado exista realmente (no quedo huerfano tras una
edicion o una regresion del backend). Es la version determinista y barata del
`groundedness` de la Guia S8: no evalua si la cita es *semanticamente*
correcta (eso lo hace `rubric_llm`), solo que la cita no esta rota.
"""
from __future__ import annotations

from ..models import Observation, Score, TestCase
from .base import EvaluatorContext


class CitationSupportEvaluator:
    id = "citation_support"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        traz = observation.output.get("trazabilidad") or {}
        trazas = traz.get("trazas", [])
        if not trazas:
            requerido = bool(case.expected.get("citation_required"))
            if requerido:
                return Score(
                    evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                    value=0.0, passed=False, detail="se exigian citas y no hay ninguna",
                )
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=1.0, passed=True, detail="sin citas y no se exigian",
            )
        soportadas = [t for t in trazas if t.get("hecho")]
        rotas = [t.get("bullet_key") for t in trazas if not t.get("hecho")]
        value = len(soportadas) / len(trazas)
        threshold = case.thresholds.get("citation_support", 0.90)
        passed = value >= threshold
        detail = f"{len(soportadas)}/{len(trazas)} citas resueltas"
        if rotas:
            detail += f"; huerfanas: {rotas[:5]}"
        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=value, passed=passed, detail=detail,
        )
