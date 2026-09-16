from conftest import make_case, make_context, make_observation

from robot_qa.evaluators.required_fact import RequiredFactEvaluator


def test_hecho_presente_pasa():
    case = make_case(expected={"required_facts": ["JAF Arica y Parinacota"]})
    obs = make_observation(output={"contenido": {"resumen_ejecutivo": ["La JAF Arica y Parinacota actuo en Arica."]}})
    score = RequiredFactEvaluator().evaluate(case, obs, make_context())
    assert score.passed
    assert score.value == 1.0


def test_ignora_acentos_y_mayusculas():
    case = make_case(expected={"required_facts": ["Concepción"]})
    obs = make_observation(output={"contenido": {"resumen_ejecutivo": ["actividad en CONCEPCION"]}})
    score = RequiredFactEvaluator().evaluate(case, obs, make_context())
    assert score.passed


def test_hecho_faltante_falla():
    case = make_case(expected={"required_facts": ["Iquique"]})
    obs = make_observation(output={"contenido": {"resumen_ejecutivo": ["actividad en Arica"]}})
    score = RequiredFactEvaluator().evaluate(case, obs, make_context())
    assert not score.passed
    assert "Iquique" in score.detail


def test_umbral_parcial_permite_perder_algunos():
    case = make_case(expected={"required_facts": ["A", "B", "C"]}, thresholds={"required_fact": 0.6})
    obs = make_observation(output={"contenido": {"resumen_ejecutivo": ["A y B aparecen"]}})
    score = RequiredFactEvaluator().evaluate(case, obs, make_context())
    assert score.passed  # 2/3 = 0.67 >= 0.6


def test_sin_facts_declarados_no_bloquea():
    case = make_case()
    obs = make_observation(output={"contenido": {}})
    score = RequiredFactEvaluator().evaluate(case, obs, make_context())
    assert score.passed


def test_usa_ground_truth_del_contexto_si_el_caso_no_declara():
    case = make_case(case_id="RAG-CTX")
    obs = make_observation(case_id="RAG-CTX", output={"contenido": {"resumen_ejecutivo": ["hay un hecho X"]}})
    ctx = make_context(ground_truth={"RAG-CTX": {"required_facts": ["hecho Y"]}})
    score = RequiredFactEvaluator().evaluate(case, obs, ctx)
    assert not score.passed
