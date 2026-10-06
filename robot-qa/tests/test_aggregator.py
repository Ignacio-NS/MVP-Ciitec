"""Prueba el gate de liberacion (Guia ROBOT_QA S11) sin tocar red ni LLM."""
from conftest import make_case

from robot_qa.models import CampaignResult, CaseResult, Gate, Score, Verdict
from robot_qa.reporting.aggregator import compute_metrics, decide_gate


def _case_result(case_id: str, verdict: Verdict, *, critical_fail: bool = False) -> CaseResult:
    case = make_case(case_id=case_id)
    passed = verdict == Verdict.PASS
    scores = [Score(evaluator_id="schema", case_id=case_id, repetition=0, value=1.0 if passed else 0.0,
                     passed=passed, critical=critical_fail)]
    return CaseResult(case=case, observations=[], scores=scores, verdict=verdict)


def _campaign(cases: list[CaseResult]) -> CampaignResult:
    return CampaignResult(run_id="t", campaign="t", started_at="now", cases=cases)


def test_gate_pass_cuando_todo_pasa():
    result = _campaign([_case_result("C1", Verdict.PASS), _case_result("C2", Verdict.PASS)])
    metrics = compute_metrics(result)
    gate, _ = decide_gate(result, metrics, {"task_success_rate": 0.9})
    assert gate == Gate.PASS


def test_gate_reject_por_fallo_critico():
    result = _campaign([
        _case_result("C1", Verdict.PASS),
        _case_result("C2", Verdict.FAIL, critical_fail=True),
    ])
    metrics = compute_metrics(result)
    gate, reason = decide_gate(result, metrics, {"task_success_rate": 0.5})
    assert gate == Gate.REJECT
    assert "C2" in reason


def test_gate_reject_por_baja_tasa_de_exito():
    result = _campaign([_case_result("C1", Verdict.PASS)] + [_case_result(f"F{i}", Verdict.FAIL) for i in range(4)])
    metrics = compute_metrics(result)
    gate, reason = decide_gate(result, metrics, {"task_success_rate": 0.9})
    assert gate == Gate.REJECT
    assert "task_success_rate" in reason


def test_gate_human_review_por_cola_excedida():
    result = _campaign(
        [_case_result("C1", Verdict.PASS)] + [_case_result(f"H{i}", Verdict.HUMAN_REVIEW) for i in range(3)]
    )
    metrics = compute_metrics(result)
    gate, reason = decide_gate(result, metrics, {"task_success_rate": 0.1, "allowed_pending_review": 1})
    assert gate == Gate.HUMAN_REVIEW


def test_metrics_incluyen_tasas_basicas():
    result = _campaign([_case_result("C1", Verdict.PASS), _case_result("C2", Verdict.FAIL)])
    metrics = compute_metrics(result)
    assert metrics["n_cases"] == 2
    assert metrics["task_success_rate"] == 0.5
    assert metrics["fail_rate"] == 0.5
