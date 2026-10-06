"""Evaluador determinista de nivel 2 (Guia S7): comparacion con referencia.

Compara el briefing generado contra `required_facts`: la lista de hechos que
DEBEN aparecer. Se declaran directamente en `case.expected.required_facts`
(formato YAML de la Guia S6) o, si el caso no los declara, se buscan en el
ground truth sintetico (`datasets/references/ground_truth.json`, generado por
`scripts/gen_corpus.py --ground-truth`) indexado por `case_id`.
"""
from __future__ import annotations

from ..models import Observation, Score, TestCase
from ..text_utils import flatten_text, normalize
from .base import EvaluatorContext


class RequiredFactEvaluator:
    id = "required_fact"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        facts = case.expected.get("required_facts")
        if not facts:
            gt = context.ground_truth.get(case.case_id, {})
            facts = gt.get("required_facts", [])
        if not facts:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=1.0, passed=True, detail="sin required_facts declarados (caso no aplica)",
            )
        haystack = normalize(flatten_text(observation.output.get("contenido")))
        faltantes = [f for f in facts if normalize(str(f)) not in haystack]
        value = (len(facts) - len(faltantes)) / len(facts)
        threshold = case.thresholds.get("required_fact", 1.0)
        passed = value >= threshold
        detail = "todos los hechos requeridos presentes" if not faltantes else f"faltan: {faltantes}"
        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=value, passed=passed, detail=detail,
        )
