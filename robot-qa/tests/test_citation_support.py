from conftest import make_case, make_context, make_observation

from robot_qa.evaluators.citation_support import CitationSupportEvaluator


def _trazas(*resueltas_no_resueltas):
    trazas = []
    for i, resuelta in enumerate(resueltas_no_resueltas):
        trazas.append({
            "bullet_key": f"b{i}",
            "hecho_id": f"h{i}",
            "hecho": {"evento": "algo paso"} if resuelta else None,
        })
    return {"trazas": trazas}


def test_todas_las_citas_resueltas_pasa():
    case = make_case()
    obs = make_observation(output={"trazabilidad": _trazas(True, True, True)})
    score = CitationSupportEvaluator().evaluate(case, obs, make_context())
    assert score.passed
    assert score.value == 1.0


def test_citas_rotas_bajan_el_valor_y_pueden_fallar():
    case = make_case(thresholds={"citation_support": 0.9})
    obs = make_observation(output={"trazabilidad": _trazas(True, False, False)})
    score = CitationSupportEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
    assert abs(score.value - 1 / 3) < 1e-9


def test_sin_citas_y_no_se_exigen_pasa():
    case = make_case(expected={"citation_required": False})
    obs = make_observation(output={"trazabilidad": {"trazas": []}})
    score = CitationSupportEvaluator().evaluate(case, obs, make_context())
    assert score.passed


def test_sin_citas_pero_se_exigen_falla():
    case = make_case(expected={"citation_required": True})
    obs = make_observation(output={"trazabilidad": {"trazas": []}})
    score = CitationSupportEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
