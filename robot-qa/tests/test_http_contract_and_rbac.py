from conftest import make_case, make_context, make_observation

from robot_qa.evaluators.http_contract import HttpContractEvaluator
from robot_qa.evaluators.rbac_leak import RbacLeakEvaluator
from robot_qa.evaluators.budget import BudgetEvaluator


def test_http_contract_status_correcto_pasa():
    case = make_case(expected={"expect_status": 200})
    obs = make_observation(http_status=200, output={})
    score = HttpContractEvaluator().evaluate(case, obs, make_context())
    assert score.passed


def test_http_contract_status_incorrecto_falla():
    case = make_case(expected={"expect_status": 200})
    obs = make_observation(http_status=500, output={})
    score = HttpContractEvaluator().evaluate(case, obs, make_context())
    assert not score.passed


def test_http_contract_not_contains_detecta_fuga():
    case = make_case(expected={"not_contains": ["CANARIO_SECRETO"]})
    obs = make_observation(output={"contenido": {"resumen_ejecutivo": ["algo CANARIO_SECRETO algo"]}})
    score = HttpContractEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
    assert "CANARIO_SECRETO" in score.detail


def test_http_contract_contains_exige_subcadena():
    case = make_case(expected={"contains": ["application/pdf"]})
    obs = make_observation(output={"export_content_type": "application/pdf"})
    score = HttpContractEvaluator().evaluate(case, obs, make_context())
    assert score.passed


def test_rbac_leak_status_esperado_pasa():
    case = make_case(expected={"expect_status": 403})
    obs = make_observation(http_status=403, output={"probed_status": 403})
    score = RbacLeakEvaluator().evaluate(case, obs, make_context())
    assert score.passed
    assert score.critical


def test_rbac_leak_fuga_detectada_falla():
    case = make_case(expected={"expect_status": 403})
    obs = make_observation(output={"probed_status": 200})
    score = RbacLeakEvaluator().evaluate(case, obs, make_context())
    assert not score.passed


def test_budget_bajo_umbral_pasa():
    case = make_case(thresholds={"latency_s": 10})
    obs = make_observation(latency_ms=2000)
    score = BudgetEvaluator().evaluate(case, obs, make_context())
    assert score.passed
    assert score.value == 2.0


def test_budget_sobre_umbral_falla():
    case = make_case(thresholds={"latency_s": 1})
    obs = make_observation(latency_ms=5000)
    score = BudgetEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
