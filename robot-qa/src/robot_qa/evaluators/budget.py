"""Evaluador determinista de nivel 1 (Guia S7): rendimiento y economia.

Controla la latencia extremo a extremo contra un umbral por caso (por
ejemplo, RNF-004: 50 documentos < 180s). `value` es la latencia en segundos
(no una metrica 0..1): el reportero la usa directo para calcular p50/p95.

Limitacion documentada (ver `adapters/api_adapter.py`): la API de MVP-Ciitec
no expone tokens ni costo del LLM en sus respuestas, asi que este evaluador
NO puede medir `cost_per_successful_task` de la Guia S7 salvo que el SUT
empiece a loguear esa metrica. Se deja `tokens_in/out/cost_usd` en None y se
documenta como limitacion conocida en el informe final.
"""
from __future__ import annotations

from ..models import Observation, Score, TestCase
from .base import EvaluatorContext


class BudgetEvaluator:
    id = "budget"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        latency_s = observation.latency_ms / 1000.0
        threshold = case.thresholds.get("latency_s")
        if threshold is None:
            threshold = context.thresholds.get("default_latency_s", 180.0)
        passed = not observation.error and latency_s <= threshold
        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=latency_s, passed=passed,
            detail=f"{latency_s:.1f}s (umbral {threshold:.0f}s)"
            + (f"; error: {observation.error}" if observation.error else ""),
        )
