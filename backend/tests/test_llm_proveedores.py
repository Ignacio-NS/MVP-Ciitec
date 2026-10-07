"""Registro de proveedores LLM: selección por LLM_PROVIDER, claves faltantes, proveedor local,
modo JSON, Claude y registro de uso. Sin red: los clientes HTTP se reemplazan por simulados."""
import json
import logging
import sys
from types import SimpleNamespace

import pytest

from app.llm import provider as P
from app.llm.provider import LLMError

CLAVES = {
    "gemini_api_key": "", "anthropic_api_key": "", "deepseek_api_key": "", "groq_api_key": "",
    "github_token": "", "llm_base_url": "", "llm_api_key": "", "llm_model": "",
    "local_llm_model": "", "local_llm_api_key": "", "llm_json_mode": True,
    "local_llm_base_url": "http://localhost:11434/v1",
}


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    """Sin claves ni red: cada prueba parte de una configuración vacía y sin esperas de backoff."""
    for k, v in CLAVES.items():
        monkeypatch.setattr(P.settings, k, v)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)


def cfg(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setattr(P.settings, k, v)


# ---------------------------------------------------------------- Anthropic simulado
class _ErrAuth(Exception):
    pass


class _AnthropicFalso:
    """Cliente simulado del SDK `anthropic`: registra los kwargs de messages.stream()."""

    def __init__(self, mensajes=None, falla=None):
        self.mensajes = list(mensajes or [])
        self.falla = falla
        self.llamadas = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kw):
        self.llamadas.append(kw)
        if self.falla:
            raise self.falla
        return _Ctx(self.mensajes.pop(0))


class _Ctx:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return SimpleNamespace(get_final_message=lambda: self.msg)

    def __exit__(self, *a):
        return False


def _msg(texto, stop="end_turn", tin=11, tout=7):
    return SimpleNamespace(
        stop_reason=stop,
        content=[SimpleNamespace(type="thinking", text="razonamiento"), SimpleNamespace(type="text", text=texto)],
        usage=SimpleNamespace(input_tokens=tin, output_tokens=tout),
    )


@pytest.fixture
def anthropic_falso(monkeypatch):
    """Instala un módulo `anthropic` falso (el SDK real no se necesita para estas pruebas)."""
    holder = SimpleNamespace(cliente=None)

    def fabrica(api_key=None):
        return holder.cliente

    mod = SimpleNamespace(Anthropic=fabrica, AuthenticationError=_ErrAuth,
                          PermissionDeniedError=type("PD", (Exception,), {}),
                          NotFoundError=type("NF", (Exception,), {}),
                          BadRequestError=type("BR", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    holder.cliente = _AnthropicFalso()
    return holder


# ---------------------------------------------------------------- Cliente OpenAI simulado
class _OpenAIFalso:
    """Devuelve las respuestas en orden y registra los kwargs de chat.completions.create()."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.kwargs = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.kwargs.append(kw)
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _resp(contenido, finish="stop", pin=None, pout=None):
    usage = SimpleNamespace(prompt_tokens=pin, completion_tokens=pout) if pin is not None else None
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=contenido), finish_reason=finish)],
        usage=usage,
    )


# ================================================================ Selección por LLM_PROVIDER
CASOS = [
    ("gemini", dict(gemini_api_key="k"), P.GeminiProvider),
    ("deepseek", dict(deepseek_api_key="k"), P.DeepSeekProvider),
    ("groq", dict(groq_api_key="k"), P.GroqProvider),
    ("github", dict(github_token="k"), P.GitHubProvider),
    ("openai_compat", dict(llm_base_url="https://gw.interno/v1", llm_api_key="k", llm_model="m"),
     P.OpenAICompatProvider),
    ("local", dict(local_llm_model="llama3"), P.LocalLLMProvider),
    ("anthropic", dict(anthropic_api_key="k"), P.AnthropicProvider),
]


@pytest.mark.parametrize("valor,conf,clase", CASOS)
def test_selecciona_cada_proveedor(monkeypatch, anthropic_falso, valor, conf, clase):
    cfg(monkeypatch, llm_provider=valor, **conf)
    p = P.get_llm_provider()
    assert type(p) is clase and p.nombre == valor


def test_valor_normalizado(monkeypatch):
    cfg(monkeypatch, llm_provider="  GeMiNi ", gemini_api_key="k")
    assert isinstance(P.get_llm_provider(), P.GeminiProvider)


def test_registro_cubre_todos_los_valores_documentados():
    assert set(P._PROVIDERS) == {"gemini", "anthropic", "deepseek", "groq", "github", "openai_compat", "local"}
    assert all(issubclass(c, P.LLMProvider) for c in P._PROVIDERS.values())


def test_gemini_es_el_defecto_de_la_configuracion():
    from app.config import Settings
    assert Settings.model_fields["llm_provider"].default == "gemini"


def test_valor_desconocido_falla_listando_los_validos(monkeypatch):
    cfg(monkeypatch, llm_provider="gpt-9", deepseek_api_key="k")  # tener clave de DeepSeek NO debe hacerlo caer ahí
    with pytest.raises(LLMError) as e:
        P.get_llm_provider()
    msg = str(e.value)
    assert "gpt-9" in msg and "no es válido" in msg
    for v in ("gemini", "anthropic", "deepseek", "groq", "github", "openai_compat", "local"):
        assert v in msg


# ================================================================ Clave / configuración faltante
@pytest.mark.parametrize("valor,variable", [
    ("gemini", "GEMINI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("github", "GITHUB_TOKEN"),
    ("openai_compat", "LLM_BASE_URL"),
    ("local", "LOCAL_LLM_MODEL"),
])
def test_falta_configuracion_error_claro(monkeypatch, valor, variable):
    cfg(monkeypatch, llm_provider=valor)
    with pytest.raises(LLMError, match=variable):
        P.get_llm_provider()


def test_openai_compat_exige_clave_y_modelo(monkeypatch):
    cfg(monkeypatch, llm_provider="openai_compat", llm_base_url="https://gw/v1")
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        P.get_llm_provider()
    cfg(monkeypatch, llm_api_key="k")
    with pytest.raises(LLMError, match="LLM_MODEL"):
        P.get_llm_provider()


# ================================================================ Proveedor local
def test_local_sin_clave_ni_internet(monkeypatch):
    cfg(monkeypatch, llm_provider="local", local_llm_model="qwen")
    p = P.get_llm_provider()
    assert "localhost:11434/v1" in str(p.client.base_url)   # URL por defecto de Ollama
    assert p.client.api_key == "local"                      # clave ficticia: el SDK exige una no vacía
    assert p.model == "qwen"


def test_local_funcionan_las_cuatro_operaciones(monkeypatch):
    cfg(monkeypatch, llm_provider="local", local_llm_model="qwen")
    p = P.get_llm_provider()
    p.client = _OpenAIFalso([
        _resp(json.dumps({"hechos": [{"evento": "Incendio en Temuco"}]})),
        _resp(json.dumps({"resumen_ejecutivo": ["a"]})),
        _resp(json.dumps({"contradicciones": [{"descripcion": "x", "hechos_involucrados": ["1", "2"]}]})),
        _resp(json.dumps({"titulo": "T", "bloques": [{"tipo": "texto", "texto": "x"}], "trazabilidad": {}})),
    ])
    assert p.extraer_hechos("texto")[0]["evento"] == "Incendio en Temuco"
    assert p.sintetizar_briefing([], {})["resumen_ejecutivo"] == ["a"]
    assert p.detectar_contradicciones([{"id": "1"}, {"id": "2"}])[0]["descripcion"] == "x"
    assert p.completar_hoja([], "ctx", {"id": "h1"})["titulo"] == "T"
    assert all(k["model"] == "qwen" for k in p.client.kwargs)


# ================================================================ Modo JSON
@pytest.mark.parametrize("modo,esperado", [(True, True), (False, False)])
def test_modo_json_configurable(monkeypatch, modo, esperado):
    cfg(monkeypatch, llm_provider="openai_compat", llm_base_url="https://gw/v1", llm_api_key="k",
        llm_model="m", llm_json_mode=modo)
    p = P.get_llm_provider()
    p.client = _OpenAIFalso([_resp('{"a": 1}')])
    assert p._chat_json("sys", "user") == {"a": 1}
    enviado = p.client.kwargs[0]
    assert ("response_format" in enviado) is esperado
    if esperado:
        assert enviado["response_format"] == {"type": "json_object"}


def test_modo_json_apagado_repara_json_mal_formado(monkeypatch):
    cfg(monkeypatch, llm_provider="openai_compat", llm_base_url="https://gw/v1", llm_api_key="k",
        llm_model="m", llm_json_mode=False)
    p = P.get_llm_provider()
    p.client = _OpenAIFalso([_resp('```json\n{"resumen_ejecutivo": ["a"],}\n```')])
    assert p._chat_json("sys", "user")["resumen_ejecutivo"] == ["a"]


# ================================================================ Claude (SDK oficial)
def test_anthropic_llamada_sin_temperature_ni_thinking(monkeypatch, anthropic_falso):
    cfg(monkeypatch, llm_provider="anthropic", anthropic_api_key="k", anthropic_model="claude-x")
    anthropic_falso.cliente = _AnthropicFalso([_msg('{"a": 1}')])
    p = P.get_llm_provider()
    assert p._chat_json("SYS", "USER", "sintetizar_briefing") == {"a": 1}   # ignora el bloque 'thinking'
    kw = anthropic_falso.cliente.llamadas[0]
    assert kw["model"] == "claude-x" and kw["system"] == "SYS"
    assert kw["messages"] == [{"role": "user", "content": "USER"}]
    assert "temperature" not in kw and "thinking" not in kw
    assert kw["max_tokens"] == P.settings.llm_max_output_tokens


def test_anthropic_truncado_reintenta_con_mas_tokens(monkeypatch, anthropic_falso):
    cfg(monkeypatch, llm_provider="anthropic", anthropic_api_key="k")
    anthropic_falso.cliente = _AnthropicFalso([_msg('{"a": "cortad', stop="max_tokens"), _msg('{"a": 1}')])
    p = P.get_llm_provider()
    assert p._chat_json("s", "u") == {"a": 1}
    usados = [c["max_tokens"] for c in anthropic_falso.cliente.llamadas]
    assert usados[0] == P.settings.llm_max_output_tokens and usados[1] > usados[0]


def test_anthropic_rechazo_no_se_reintenta(monkeypatch, anthropic_falso):
    cfg(monkeypatch, llm_provider="anthropic", anthropic_api_key="k")
    anthropic_falso.cliente = _AnthropicFalso([_msg("", stop="refusal")])
    with pytest.raises(LLMError, match="rechaz"):
        P.get_llm_provider()._chat_json("s", "u")
    assert len(anthropic_falso.cliente.llamadas) == 1


def test_anthropic_clave_invalida_falla_de_inmediato(monkeypatch, anthropic_falso):
    cfg(monkeypatch, llm_provider="anthropic", anthropic_api_key="mala")
    anthropic_falso.cliente = _AnthropicFalso(falla=_ErrAuth("401"))
    with pytest.raises(LLMError, match="no recuperable"):
        P.get_llm_provider()._chat_json("s", "u")
    assert len(anthropic_falso.cliente.llamadas) == 1   # no gasta los reintentos en un error definitivo


# ================================================================ Registro de uso
def _openai_compat(monkeypatch, respuestas):
    cfg(monkeypatch, llm_provider="openai_compat", llm_base_url="https://gw/v1", llm_api_key="k",
        llm_model="modelo-x", llm_max_retries=3)
    p = P.get_llm_provider()
    p.client = _OpenAIFalso(respuestas)
    return p


def test_registro_de_uso_con_metadatos(monkeypatch, caplog):
    p = _openai_compat(monkeypatch, [_resp('{"k": 1}', pin=123, pout=45)])
    with caplog.at_level(logging.INFO, logger="app.llm.provider"):
        p._chat_json("s", "u", "extraer_hechos")
    lineas = [r.getMessage() for r in caplog.records if r.getMessage().startswith("llm_call")]
    assert len(lineas) == 1
    for trozo in ("provider=openai_compat", "model=modelo-x", "op=extraer_hechos", "intento=1/3",
                  "tokens_in=123", "tokens_out=45", "resultado=ok", "latencia_s="):
        assert trozo in lineas[0], trozo


def test_registro_de_uso_nunca_incluye_contenido(monkeypatch, caplog):
    secreto = "DOCUMENTO-CLASIFICADO-XYZ"
    p = _openai_compat(monkeypatch, [RuntimeError(f"fallo con {secreto}"),
                                     _resp(json.dumps({"k": secreto}), pin=5, pout=6)])
    with caplog.at_level(logging.DEBUG):
        p._chat_json(f"SISTEMA {secreto}", f"USUARIO {secreto}", "completar_hoja")
    assert secreto not in caplog.text
    assert "error=RuntimeError" in caplog.text and "intento=1/3" in caplog.text and "intento=2/3" in caplog.text
