"""Motor de IA intercambiable: registro, adaptadores, configuración efectiva y presupuesto.

Todas las pruebas usan clientes simulados: no llaman a ningún servicio real.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.llm import ajustes as aj_mod
from app.llm import catalogo, presupuesto
from app.llm.ajustes import ConfigIAError, construir
from app.llm.provider import (
    AnthropicProvider,
    LLMError,
    LocalLLMProvider,
    OpenAICompatProvider,
    _extraer_json,
    crear_proveedor,
    get_llm_provider,
    probar_conexion,
)
from app.pipeline import extraccion


# ---------------------------------------------------------------------------
#  Clientes falsos
# ---------------------------------------------------------------------------
class _OpenAIFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.llamadas.append(kw)
        contenido, finish = self.respuestas.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=contenido), finish_reason=finish)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


class _AnthropicFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.llamadas.append(kw)
        texto, stop = self.respuestas.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=texto)],
            stop_reason=stop,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


@pytest.fixture
def env(monkeypatch):
    """Permite cambiar variables de `settings` dentro de una prueba."""
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(aj_mod, "_leer_fila_vigente", lambda: None)
    aj_mod.invalidar_cache()
    yield _set
    aj_mod.invalidar_cache()


def _compat(**cambios):
    base = {"base_url": "http://llm.local/v1", "modelo": "m"}
    base.update(cambios)
    return construir("openai_compat", base, origen="env")


# ---------------------------------------------------------------------------
#  Registro: falla cerrado
# ---------------------------------------------------------------------------
def test_proveedor_desconocido_falla_con_lista_de_validos():
    with pytest.raises(ConfigIAError) as e:
        construir("gemeni", {}, origen="env")
    assert "gemini" in str(e.value) and "local" in str(e.value)


def test_get_llm_provider_no_cae_en_silencio_a_otro_proveedor(env):
    env(llm_provider="gemeni")
    with pytest.raises(LLMError, match="Valores válidos"):
        get_llm_provider()


def test_catalogo_incluye_los_proveedores_documentados():
    assert set(catalogo.nombres()) >= {
        "gemini", "openai", "anthropic", "deepseek", "mistral", "groq", "github", "openai_compat", "local",
    }


@pytest.mark.parametrize("nombre", ["gemini", "openai", "deepseek", "mistral", "groq", "github"])
def test_presets_de_nube_usan_el_adaptador_openai(nombre):
    aj = construir(nombre, {"api_key": "sk-prueba-1234"}, origen="env")
    assert isinstance(crear_proveedor(aj, _OpenAIFalso([])), OpenAICompatProvider)
    assert aj.base_url.startswith("https://")


def test_anthropic_usa_adaptador_nativo():
    aj = construir("anthropic", {"api_key": "sk-ant-1234"}, origen="env")
    assert isinstance(crear_proveedor(aj, _AnthropicFalso([])), AnthropicProvider)


def test_local_no_exige_clave_y_usa_su_clase():
    aj = construir("local", {}, origen="env")
    assert aj.api_key == "" and aj.resguardo == "MAXIMO"
    assert isinstance(crear_proveedor(aj, _OpenAIFalso([])), LocalLLMProvider)


def test_falta_clave_en_proveedor_de_nube(env):
    env(openai_api_key="")
    with pytest.raises(ConfigIAError, match="API key"):
        construir("openai", {}, origen="env")


def test_openai_compat_exige_url_y_modelo(env):
    env(llm_base_url="", llm_model="")
    with pytest.raises(ConfigIAError, match="modelo"):
        construir("openai_compat", {"base_url": "http://x/v1"}, origen="env")
    with pytest.raises(ConfigIAError, match="URL"):
        construir("openai_compat", {"modelo": "m"}, origen="env")


def test_url_sin_esquema_es_invalida():
    with pytest.raises(ConfigIAError, match="URL inválida"):
        _compat(base_url="llm.local:11434/v1")


# ---------------------------------------------------------------------------
#  Parámetros que varían por servicio
# ---------------------------------------------------------------------------
def test_kwargs_openai_compat_por_defecto():
    p = crear_proveedor(_compat(), _OpenAIFalso([]))
    kw = p._kwargs("s", "u", 1000)
    assert kw["max_tokens"] == 1000
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["temperature"] == 0.1
    assert "extra_body" not in kw


def test_kwargs_sin_modo_json_sin_temperatura_y_con_extra():
    aj = _compat(json_mode=False, temperature="none", token_param="max_completion_tokens",
                 extra_params='{"reasoning_effort": "none"}')
    kw = crear_proveedor(aj, _OpenAIFalso([]))._kwargs("s", "u", 500)
    assert "response_format" not in kw and "temperature" not in kw and "max_tokens" not in kw
    assert kw["max_completion_tokens"] == 500
    assert kw["extra_body"] == {"reasoning_effort": "none"}


def test_preset_openai_no_envia_temperature_y_usa_max_completion_tokens():
    aj = construir("openai", {"api_key": "sk-1234"}, origen="env")
    kw = crear_proveedor(aj, _OpenAIFalso([]))._kwargs("s", "u", 100)
    assert "temperature" not in kw and kw["max_completion_tokens"] == 100


def test_gemini_apaga_thinking_solo_en_2_5():
    assert construir("gemini", {"api_key": "k-1234", "modelo": "gemini-2.5-flash"}, origen="env") \
        .extra_params == {"reasoning_effort": "none"}
    assert construir("gemini", {"api_key": "k-1234", "modelo": "gemini-3.8-flash"}, origen="env") \
        .extra_params == {}


def test_groq_ya_no_necesita_su_sdk():
    aj = construir("groq", {"api_key": "gsk-1234"}, origen="env")
    assert aj.base_url == "https://api.groq.com/openai/v1" and aj.adaptador == "openai"


def test_extra_params_invalido():
    with pytest.raises(ConfigIAError, match="JSON"):
        _compat(extra_params="{no es json")


# ---------------------------------------------------------------------------
#  Respuestas sin modo JSON
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("texto", [
    '{"hechos": []}',
    '```json\n{"hechos": []}\n```',
    'Claro, aquí está el resultado:\n{"hechos": []}\nSaludos.',
    '<think>razono...{no json}</think>\n{"hechos": []}',
])
def test_extraer_json_tolera_texto_alrededor(texto):
    assert _extraer_json(texto) == '{"hechos": []}'


def test_modelo_sin_modo_json_que_agrega_preambulo():
    c = _OpenAIFalso([('Aquí tienes: {"hechos": [{"evento": "x", "texto_origen": "y"}]}', "stop")])
    p = crear_proveedor(_compat(json_mode=False), c)
    assert p.extraer_hechos("doc")[0]["evento"] == "x"


# ---------------------------------------------------------------------------
#  Adaptador Anthropic
# ---------------------------------------------------------------------------
def test_anthropic_system_aparte_sin_temperature_y_parseo():
    c = _AnthropicFalso([('{"hechos": [{"evento": "e", "texto_origen": "t"}]}', "end_turn")])
    p = crear_proveedor(construir("anthropic", {"api_key": "sk-ant-1234"}, origen="env"), c)
    assert p.extraer_hechos("documento")[0]["evento"] == "e"
    kw = c.llamadas[0]
    assert kw["system"].startswith("Eres un analista") and "temperature" not in kw
    assert kw["messages"] == [{"role": "user", "content": "documento"}]


def test_anthropic_truncado_escala_tokens():
    c = _AnthropicFalso([('{"resumen_ejecutivo": ["a"', "max_tokens"), ('{"resumen_ejecutivo": ["a"]}', "end_turn")])
    p = crear_proveedor(construir("anthropic", {"api_key": "sk-ant-1234"}, origen="env"), c)
    p.max_output_tokens, p.max_output_techo = 1000, 4000
    assert p._chat_json("s", "u")["resumen_ejecutivo"] == ["a"]
    assert [k["max_tokens"] for k in c.llamadas] == [1000, 2000]


# ---------------------------------------------------------------------------
#  Configuración efectiva: interfaz vs .env
# ---------------------------------------------------------------------------
def _fila(**kw):
    base = dict(proveedor="local", modelo=None, base_url=None, api_key=None, json_mode=None, temperature=None,
                token_param=None, extra_params=None, context_tokens=None, timeout_s=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_sin_fila_manda_el_env(env):
    env(llm_provider="local", local_llm_model="qwen3.8:27b")
    aj = aj_mod.resolver()
    assert aj.origen == "env" and aj.modelo == "qwen3.8:27b"


def test_fila_de_la_interfaz_manda_sobre_el_env(env, monkeypatch):
    env(llm_provider="gemini", gemini_api_key="g-key-1234", llm_model="gemini-2.5-flash")
    monkeypatch.setattr(aj_mod, "_leer_fila_vigente", lambda: _fila(proveedor="local", modelo="gpt-oss:20b"))
    aj = aj_mod.resolver()
    # LLM_MODEL del .env pertenece a Gemini: no debe contaminar al proveedor elegido en la interfaz.
    assert aj.origen == "ui" and aj.proveedor == "local" and aj.modelo == "gpt-oss:20b"


def test_fila_sin_clave_usa_la_del_servidor(env, monkeypatch):
    env(llm_provider="local", anthropic_api_key="sk-ant-servidor")
    monkeypatch.setattr(aj_mod, "_leer_fila_vigente", lambda: _fila(proveedor="anthropic"))
    assert aj_mod.resolver().api_key == "sk-ant-servidor"


def test_proveedor_no_permitido_vuelve_al_env(env, monkeypatch):
    env(llm_provider="local", llm_proveedores_permitidos="local")
    monkeypatch.setattr(aj_mod, "_leer_fila_vigente",
                        lambda: _fila(proveedor="openai", modelo="gpt-6-luna", api_key="sk-1234"))
    aj = aj_mod.resolver()
    assert aj.proveedor == "local" and aj.origen == "env"


def test_bd_caida_vuelve_al_env(env, monkeypatch):
    env(llm_provider="local")

    def _falla():
        raise RuntimeError("relation llm_config does not exist")

    monkeypatch.setattr(aj_mod, "_leer_fila_vigente", _falla)
    assert aj_mod.resolver().origen == "env"


def test_vista_publica_nunca_incluye_la_clave():
    aj = construir("anthropic", {"api_key": "sk-ant-secreta-9876"}, origen="ui")
    pub = aj.publico()
    assert "api_key" not in pub and "sk-ant-secreta" not in str(pub)
    assert pub["api_key_configurada"] is True and pub["api_key_sufijo"] == "9876"


# ---------------------------------------------------------------------------
#  Presupuesto de contexto (modelos locales)
# ---------------------------------------------------------------------------
def test_sin_ventana_declarada_se_mantienen_los_topes():
    aj = _compat()
    assert presupuesto.limites_sintesis(aj) == (
        settings.synth_max_hechos, settings.synth_max_contexto_chars, settings.synth_max_chars_por_fuente,
    )
    assert presupuesto.max_chars_extraccion(aj) == 0


def test_ventana_chica_reduce_entrada_y_salida():
    aj = _compat(context_tokens=16000)
    assert aj.max_output_tokens <= 16000 * 0.45
    hechos, ctx, por_fuente = presupuesto.limites_sintesis(aj)
    assert hechos < settings.synth_max_hechos and ctx < settings.synth_max_contexto_chars
    assert por_fuente <= ctx
    # la entrada estimada + la salida caben en la ventana
    assert ctx / presupuesto.CHARS_POR_TOKEN + hechos * 110 + aj.max_output_tokens <= 16000


def test_fragmentar_respeta_tamano_y_solapa():
    texto = "\n\n".join(f"Párrafo {i}: " + "x" * 300 for i in range(40))
    trozos = presupuesto.fragmentar(texto, 2000)
    assert len(trozos) > 1 and all(len(t) <= 2000 for t in trozos)
    assert trozos[1][:50] in trozos[0] or trozos[0][-200:] in trozos[1]


def test_extraccion_por_fragmentos_sin_duplicar(monkeypatch):
    monkeypatch.setattr(extraccion.embeddings, "embed", lambda t: [0.0] * 384)
    llamadas = []

    class _Stub:
        aj = _compat(context_tokens=4000)

        def extraer_hechos(self, texto):
            llamadas.append(len(texto))
            return [{"evento": "Mismo evento", "texto_origen": "cita"}]

    texto = "\n".join("línea de bitácora " * 20 for _ in range(200))
    hechos = extraccion.extraer(texto, _Stub())
    assert len(llamadas) > 1          # el documento se partió
    assert len(hechos) == 1           # el hecho repetido por el solape no se duplica


# ---------------------------------------------------------------------------
#  Prueba de conexión
# ---------------------------------------------------------------------------
def test_probar_conexion_ok(monkeypatch):
    aj = _compat()
    monkeypatch.setattr("app.llm.provider.crear_proveedor",
                        lambda a, client=None: OpenAICompatProvider(a, _OpenAIFalso([('{"ok": true}', "stop")])))
    r = probar_conexion(aj)
    assert r["ok"] is True and r["modelo"] == "m"


def test_probar_conexion_reporta_error_sin_exponer_clave(monkeypatch):
    aj = construir("openai", {"api_key": "sk-super-secreta-0000"}, origen="ui")

    class _Roto:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(
            RuntimeError("401 unauthorized"))))

    monkeypatch.setattr("app.llm.provider.crear_proveedor", lambda a, client=None: OpenAICompatProvider(a, _Roto()))
    r = probar_conexion(aj)
    assert r["ok"] is False and "401" in r["error"] and "sk-super-secreta" not in str(r)
