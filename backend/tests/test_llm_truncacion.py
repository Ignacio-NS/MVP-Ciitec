"""Una respuesta del LLM cortada por el tope de tokens no debe guardarse como briefing a medias."""
from types import SimpleNamespace

import pytest

from app.llm.provider import LLMError, _OpenAICompatProvider

COMPLETO = '{"resumen_ejecutivo": ["a"], "inteligencia": {"analisis_meteo": "x"}}'
TRUNCADO = '{"resumen_ejecutivo": ["a"], "personal": {"slc": {"clase_2006": "21'  # cortado a medias


def _resp(contenido: str, finish: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=contenido), finish_reason=finish)],
        usage=None,
    )


class _ClienteFalso:
    """Devuelve las respuestas en orden y registra los max_tokens pedidos."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.max_tokens: list[int] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.max_tokens.append(kw["max_tokens"])
        return self.respuestas.pop(0)


def _provider(cliente, techo=4000):
    p = _OpenAICompatProvider()
    p.client, p.model, p.max_retries = cliente, "m", 3
    p.max_output_tokens, p.max_output_techo = 1000, techo
    return p


def test_truncado_reintenta_con_mas_tokens():
    c = _ClienteFalso([_resp(TRUNCADO, "length"), _resp(COMPLETO, "stop")])
    data = _provider(c)._chat_json("sys", "user")
    assert data["inteligencia"]["analisis_meteo"] == "x"
    assert c.max_tokens == [1000, 2000]


def test_truncado_sin_techo_falla_en_vez_de_reparar():
    c = _ClienteFalso([_resp(TRUNCADO, "length")])
    with pytest.raises(LLMError, match="tope de tokens"):
        _provider(c, techo=1000)._chat_json("sys", "user")
    assert c.max_tokens == [1000]  # no devolvió el JSON "reparado" con secciones vacías


def test_json_valido_en_el_limite_se_acepta():
    c = _ClienteFalso([_resp(COMPLETO, "length")])
    assert _provider(c)._chat_json("sys", "user")["resumen_ejecutivo"] == ["a"]


def test_json_mal_formado_sin_truncar_se_repara():
    c = _ClienteFalso([_resp('{"resumen_ejecutivo": ["a"],}', "stop")])
    assert _provider(c)._chat_json("sys", "user")["resumen_ejecutivo"] == ["a"]
