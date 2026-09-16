from conftest import make_case, make_context, make_observation

from robot_qa.evaluators.schema import SchemaEvaluator


def test_pasa_con_contenido_valido(briefing_out_minimo):
    case = make_case(evaluators=["schema"])
    obs = make_observation(output={"contenido": briefing_out_minimo})
    score = SchemaEvaluator().evaluate(case, obs, make_context())
    assert score.passed
    assert score.value == 1.0


def test_falla_critico_sin_contenido():
    case = make_case()
    obs = make_observation(output={})
    score = SchemaEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
    assert score.critical


def test_falla_con_error_de_transporte():
    case = make_case()
    obs = make_observation(error="timeout de red")
    score = SchemaEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
    assert score.critical
    assert "timeout" in score.detail


def test_falla_si_resumen_ejecutivo_vacio(briefing_out_minimo):
    briefing_out_minimo["resumen_ejecutivo"] = []
    case = make_case()
    obs = make_observation(output={"contenido": briefing_out_minimo})
    score = SchemaEvaluator().evaluate(case, obs, make_context())
    assert not score.passed


def test_falla_si_no_valida_el_esquema():
    case = make_case()
    obs = make_observation(output={"contenido": {"resumen_ejecutivo": "esto deberia ser una lista, no un string"}})
    score = SchemaEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
    assert score.critical
