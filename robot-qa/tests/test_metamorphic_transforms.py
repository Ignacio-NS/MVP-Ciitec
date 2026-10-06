"""Prueba las transformaciones metamorficas puras (sin SUT, Guia ROBOT_QA S8)."""
from robot_qa.evaluators.metamorphic import _TRANSFORMS, _jaccard_palabras, _reformatear_fechas


def test_reformatear_fechas():
    assert _reformatear_fechas("El 05-05-2026 paso algo") == "El 5 de mayo de 2026 paso algo"


def test_reorder_invierte_la_lista():
    docs = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    assert _TRANSFORMS["reorder"](docs) == list(reversed(docs))


def test_remove_doc_quita_el_ultimo():
    docs = [{"name": "a", "content": "1"}, {"name": "b", "content": "2"}]
    out = _TRANSFORMS["remove_doc"](docs)
    assert len(out) == 1 and out[0]["name"] == "a"


def test_remove_doc_no_toca_lista_de_un_elemento():
    docs = [{"name": "a", "content": "1"}]
    assert _TRANSFORMS["remove_doc"](docs) == docs


def test_duplicate_doc_agrega_una_copia():
    docs = [{"name": "a", "content": "1"}]
    out = _TRANSFORMS["duplicate_doc"](docs)
    assert len(out) == 2
    assert out[1]["content"] == "1"
    assert out[1]["name"] != out[0]["name"]


def test_add_irrelevant_no_toca_los_originales():
    docs = [{"name": "a", "content": "1"}]
    out = _TRANSFORMS["add_irrelevant"](docs)
    assert len(out) == 2
    assert out[0] == docs[0]
    assert "receta" in out[1]["name"]


def test_jaccard_identico_es_uno():
    assert _jaccard_palabras(["la unidad actuo en Arica"], ["la unidad actuo en Arica"]) == 1.0


def test_jaccard_disjunto_es_cero():
    assert _jaccard_palabras(["palabras completamente distintas aqui"], ["nada tiene relacion alguna"]) == 0.0


def test_jaccard_ambos_vacios_es_uno():
    assert _jaccard_palabras([], []) == 1.0
