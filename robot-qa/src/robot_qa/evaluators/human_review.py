"""Evaluador de nivel 6 (Guia S7): revision humana, casos criticos y desacuerdos.

No decide "aprobado/rechazado" por si mismo (no reemplaza el juicio humano, Guia
S1 "Principio rector"): SOLO decide si el caso debe encolarse para revision de
una persona, y deja el registro en
`evidence/<run_id>/human_review_queue.jsonl` para que el agregador calcule
`review_queue_count` (Guia S11) y para que `robot_qa calibrate` mida luego el
acuerdo entre el juez LLM y la revision humana (criterio de aceptacion S15).

Un caso se encola si:
  - esta explicitamente marcado (`tags: [revision_humana]`), o
  - el juez LLM (`rubric_llm`, si corrio antes en la misma observacion) dio un
    puntaje limite (2-3 de 5: ni claramente bien ni claramente mal), o
  - el caso es de severidad critica y algun evaluador no-critico fallo (senal
    ambigua: no es un fallo critico automatico, pero tampoco un exito limpio).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import Observation, Score, TestCase
from .base import EvaluatorContext


class HumanReviewEvaluator:
    id = "human_review"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        reasons: list[str] = []

        if "revision_humana" in case.tags:
            reasons.append("caso marcado explicitamente para revision")

        for s in context.sibling_scores:
            if s.evaluator_id == "rubric_llm" and 0.35 <= s.value < 0.65:
                reasons.append(f"juez LLM en zona limite ({s.value * 5:.0f}/5)")

        if case.severity == "critical":
            fallos_no_criticos = [s for s in context.sibling_scores if not s.passed and not s.critical]
            if fallos_no_criticos:
                reasons.append(f"severidad critica con {len(fallos_no_criticos)} evaluador(es) no criticos en falla")

        needs_review = bool(reasons)
        if needs_review and context.evidence_dir is not None:
            context.evidence_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "case_id": case.case_id, "repetition": observation.repetition,
                "requirement_id": case.requirement_id, "severity": case.severity,
                "reasons": reasons, "queued_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(context.evidence_dir / "human_review_queue.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=1.0, passed=True, critical=False,  # informativo: nunca hace fallar el caso por si mismo
            detail="encolado: " + "; ".join(reasons) if needs_review else "no requiere revision humana",
        )
