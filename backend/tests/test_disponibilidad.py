"""Clasificación de disponibilidad de modelos y modelos retirados."""
from app.llm import catalogo
from app.llm.disponibilidad import clasificar_error, comprobar, filtrar_chat


class _Err(Exception):
    def __init__(self, status_code=None, msg="", nombre=None):
        super().__init__(msg)
        self.status_code = status_code


def test_clasifica_codigos():
    assert clasificar_error(_Err(404, "model_not_found")) == "no_existe"
    assert clasificar_error(_Err(400, "The model `llama-3.3-70b-versatile` has been decommissioned")) == "no_existe"
    assert clasificar_error(_Err(401, "invalid api key")) == "clave"
    assert clasificar_error(_Err(403, "forbidden")) == "sin_acceso"
    assert clasificar_error(_Err(429, "rate limit, try again in 20s")) == "sin_cuota"
    assert clasificar_error(_Err(429, "quota exceeded ... limit: 0, model: gemini-3-pro")) == "sin_acceso"
    assert clasificar_error(_Err(400, "max_tokens must be at least 64")) == "disponible"
    assert clasificar_error(_Err(400, "This model only supports audio input")) == "incompatible"
    assert clasificar_error(TimeoutError("timed out")) == "error"


def test_filtra_modelos_que_no_son_de_chat():
    chat, ocultos = filtrar_chat(["gpt-oss-120b", "whisper-large-v3", "text-embedding-004",
                                  "gemini-3.5-flash", "imagen-4", "playai-tts", "llama-guard-4"])
    assert chat == ["gpt-oss-120b", "gemini-3.5-flash"]
    assert ocultos == 5


def test_ollama_no_descargado_sin_llamar_al_modelo():
    r = comprobar(None, "qwen3:8b", descargados=["gemma4:12b", "llama3.2:latest"])
    assert r["estado"] == "no_descargado"
    assert comprobar(None, "llama3.2", descargados=["llama3.2:latest"])["estado"] == "disponible"


def test_preset_no_usa_modelo_retirado():
    assert catalogo.vigente("llama-3.3-70b-versatile") == "openai/gpt-oss-120b"
    assert catalogo.vigente("gemini-3.5-flash") == "gemini-3.5-flash"
    for p in catalogo.presets().values():
        assert p.modelo not in catalogo.MODELOS_RETIRADOS
