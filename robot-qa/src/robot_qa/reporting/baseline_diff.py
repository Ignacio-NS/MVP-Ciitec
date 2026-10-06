"""Comparacion con linea base (Guia S1 'comparacion entre versiones y regresion',
Guia S15 'compara una version candidata con una linea base').

Guarda `reports/baseline.json` con `CampaignResult.model_dump()` de una
campana de referencia (tipicamente la de un commit etiquetado/aprobado) y
compara la campana actual contra ella caso por caso y metrica por metrica.
Esto es lo que permite demostrar una regresion detectada por el robot
(checklist Guia S17).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import CampaignResult, Verdict

_HIGHER_IS_BETTER = {"task_success_rate", "groundedness", "consistency_avg"}
_LOWER_IS_BETTER = {
    "fail_rate", "hallucination_rate_proxy", "attack_success_rate",
    "latency_p50_s", "latency_p95_s", "critical_failure_count", "review_queue_count",
}


def load_baseline(path: Path) -> CampaignResult | None:
    if not path.is_file():
        return None
    return CampaignResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_baseline(result: CampaignResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def compare_to_baseline(current: CampaignResult, baseline: CampaignResult, tolerance: dict | None = None) -> dict:
    tolerance = tolerance or {}
    metric_diffs: dict[str, dict] = {}
    regressions_detected = False

    for key, cur_val in current.metrics.items():
        base_val = baseline.metrics.get(key)
        if not isinstance(cur_val, (int, float)) or not isinstance(base_val, (int, float)):
            continue
        delta = cur_val - base_val
        tol = tolerance.get(key, 0.0)
        regressed = False
        if key in _HIGHER_IS_BETTER:
            regressed = delta < -tol
        elif key in _LOWER_IS_BETTER:
            regressed = delta > tol
        metric_diffs[key] = {"baseline": base_val, "current": cur_val, "delta": delta, "regressed": regressed}
        regressions_detected = regressions_detected or regressed

    base_verdicts = {cr.case.case_id: cr.verdict for cr in baseline.cases}
    new_failures = [
        cr.case.case_id for cr in current.cases
        if cr.verdict == Verdict.FAIL and base_verdicts.get(cr.case.case_id) != Verdict.FAIL
    ]
    fixed = [
        cr.case.case_id for cr in current.cases
        if cr.verdict == Verdict.PASS and base_verdicts.get(cr.case.case_id) == Verdict.FAIL
    ]
    if new_failures:
        regressions_detected = True

    return {
        "baseline_run_id": baseline.run_id,
        "current_run_id": current.run_id,
        "metric_diffs": metric_diffs,
        "new_failures": new_failures,
        "fixed": fixed,
        "regressions_detected": regressions_detected,
    }
