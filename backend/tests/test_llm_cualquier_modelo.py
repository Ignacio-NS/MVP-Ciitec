"""Que funcione CUALQUIER modelo: síntesis por secciones, catálogo de modelos del
servicio, verificación con un parte ficticio, descarga en Ollama y gateway LiteLLM.

Clientes simulados: ninguna prueba llama a un servicio real.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import openai
import pytest
from fastapi.testclient import TestClient

from app.auth.tokens import crear_token
from app.config import settings
from app.llm import ajustes as aj_mod
from app.llm import catalogo, ollama, secciones
from app.llm.ajustes import ConfigIAError, construir
from app.llm.provider import LLMError, crear_proveedor, listar_modelos, verificar_modelo
from app.main import app


# ---------------------------------------------------------------------------
#  Cliente falso que responde según la sección que se le pide
# ---------------------------------------------------------------------------
SECCION_OK = {
    "RESUMEN EJECUTIVO": {"resumen_ejecutivo": ["b1", "b2", "b3"], "asuntos_criticos": [],
                          "proyeccion_24_72h": "p", "situacion": {"resumen": "s", "aspectos": []},
                          "trazabilidad": {"resumen_ejecutivo[0]": ["h0"]}},
    "SOLO la sección PERSONAL": {"personal": {"parte_fuerza_institucional": {"total": "1240"}},
                                 "trazabilidad": {"personal.parte_fuerza_institucional.total": ["h1"]}},
    "INTELIGENCIA": {"inteligencia": {"analisis_meteo": "lluvias"}, "trazabilidad": {}},
    "OPERACIONES (CATÁSTROFE": {"operaciones": {"ops_catastrofe": [{"tipo": "incendio"}]}},
    "OPERACIONES (GUARDIÁN": {"operaciones": {"despliegue_mapa": {"mzn": "3"}}},
    "LOGÍSTICA": {"logistica": {"resumen": {"total": "10", "nop": "1"}}},
}
EXTRACCION = {"hechos": [
    {"evento": "Incendio forestal en Cerro Alto", "texto_origen": "un incendio forestal afectó"},
    {"evento": "Corte del puente Río Claro", "texto_origen": "se cortó el puente"},
    {"evento": "Evacuación de 35 familias", "texto_origen": "evacuación preventiva"},
]}


class _Router:
    """Cliente OpenAI falso. `resp(system, user)` -> (texto, finish_reason)."""

    def __init__(self, resp):
        self.resp = resp
        self.sistemas: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id="b-modelo"), SimpleNamespace(id="models/a-modelo")])

    def _create(self, **kw):
        system = kw["messages"][0]["content"]
        self.sistemas.append(system)
        texto, fin = self.resp(system, kw["messages"][1]["content"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=texto), finish_reason=fin)],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )


def _por_seccion(overrides=None):
    overrides = overrides or {}

    def resp(system, user):
        if "Extrae los hechos" in system:
            return json.dumps(EXTRACCION), "stop"
        if "verificador de conexión" in system:
            return '{"ok": true}', "stop"
        if "redacta un briefing operacional institucional" in system:  # síntesis completa
            return overrides.get("COMPLETA", ('{"resumen_ejecutivo": ["x"', "length"))
        for marca, data in SECCION_OK.items():
            if marca in system:
                if marca in overrides:
                    return overrides[marca]
                return json.dumps(data), "stop"
        raise AssertionError("prompt inesperado")
    return resp


@pytest.fixture(autouse=True)
def _rapido(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(aj_mod, "_leer_fila_vigente", lambda: None)
    aj_mod.invalidar_cache()
    yield
    aj_mod.invalidar_cache()


def _aj(**cambios):
    base = {"base_url": "http://llm.local/v1", "modelo": "chico"}
    base.update(cambios)
    return construir("local", base, origen="ui")


# ---------------------------------------------------------------------------
#  Síntesis por secciones
# ---------------------------------------------------------------------------
def test_por_secciones_une_las_seis_partes():
    cli = _Router(_por_seccion())
    p = crear_proveedor(_aj(sintesis_modo="secciones"), cli)
    out = p.sintetizar_briefing([{"id": "h0", "evento": "e"}], {"contexto_fuentes": "x"})
    assert len(cli.sistemas) == 6
    assert not any("redacta un briefing operacional institucional" in s for s in cli.sistemas)
    assert out["resumen_ejecutivo"] == ["b1", "b2", "b3"]
    assert out["personal"]["parte_fuerza_institucional"]["total"] == "1240"
    # Las dos llamadas de operaciones se mezclan en un solo bloque.
    assert out["operaciones"]["ops_catastrofe"][0]["tipo"] == "incendio"
    assert out["operaciones"]["despliegue_mapa"]["mzn"] == "3"
    assert out["trazabilidad"] == {"resumen_ejecutivo[0]": ["h0"], "personal.parte_fuerza_institucional.total": ["h1"]}
    assert out["generacion"] == {"modo": "secciones", "avisos": []}


def test_seccion_secundaria_fallida_queda_vacia_con_aviso():
    cli = _Router(_por_seccion({"LOGÍSTICA": ("esto no es json", "stop")}))
    p = crear_proveedor(_aj(sintesis_modo="secciones"), cli)
    out = p.sintetizar_briefing([], {})
    assert out["logistica"] == {}
    assert len(out["generacion"]["avisos"]) == 1 and "LOGÍSTICA" in out["generacion"]["avisos"][0]


def test_seccion_con_json_valido_pero_sin_su_parte_cuenta_como_falla():
    cli = _Router(_por_seccion({"INTELIGENCIA": ('{"hechos": []}', "stop")}))
    out = crear_proveedor(_aj(sintesis_modo="secciones"), cli).sintetizar_briefing([], {})
    assert out["inteligencia"] == {} and "INTELIGENCIA" in out["generacion"]["avisos"][0]


def test_sin_resumen_ejecutivo_no_hay_sitrep():
    cli = _Router(_por_seccion({"RESUMEN EJECUTIVO": ('{"resumen_ejecutivo": []}', "stop")}))
    with pytest.raises(LLMError, match="resumen ejecutivo"):
        crear_proveedor(_aj(sintesis_modo="secciones"), cli).sintetizar_briefing([], {})


def test_auto_rehace_por_secciones_si_la_completa_no_alcanza():
    cli = _Router(_por_seccion())  # la completa siempre llega cortada
    p = crear_proveedor(_aj(sintesis_modo="auto"), cli)
    out = p.sintetizar_briefing([], {})
    assert out["generacion"]["modo"] == "secciones (respaldo)"
    assert out["resumen_ejecutivo"] == ["b1", "b2", "b3"]
    assert any("redacta un briefing operacional institucional" in s for s in cli.sistemas)


def test_auto_con_ventana_chica_va_directo_por_secciones():
    cli = _Router(_por_seccion())
    crear_proveedor(_aj(sintesis_modo="auto", context_tokens=8192), cli).sintetizar_briefing([], {})
    assert not any("redacta un briefing operacional institucional" in s for s in cli.sistemas)


def test_auto_usa_la_completa_cuando_el_modelo_puede():
    completa = {**SECCION_OK["RESUMEN EJECUTIVO"], "logistica": {"resumen": {"total": "9"}}}
    cli = _Router(_por_seccion({"COMPLETA": (json.dumps(completa), "stop")}))
    out = crear_proveedor(_aj(sintesis_modo="auto"), cli).sintetizar_briefing([], {})
    assert len(cli.sistemas) == 1 and out["generacion"]["modo"] == "completa"


def test_modo_completa_no_cae_a_secciones():
    cli = _Router(_por_seccion())
    with pytest.raises(LLMError):
        crear_proveedor(_aj(sintesis_modo="completa"), cli).sintetizar_briefing([], {})
    assert all("redacta un briefing operacional institucional" in s for s in cli.sistemas)


def test_modo_de_sintesis_invalido_y_desde_env(monkeypatch):
    with pytest.raises(ConfigIAError, match="Modo de síntesis"):
        _aj(sintesis_modo="mitad")
    monkeypatch.setattr(settings, "llm_sintesis_modo", "secciones")
    assert _aj().sintesis_modo == "secciones"


def test_los_prompts_de_seccion_piden_la_misma_estructura_que_la_completa():
    claves = set()
    for s in secciones.SECCIONES:
        claves |= set(json.loads(s.esquema).keys())
    assert claves == {"resumen_ejecutivo", "asuntos_criticos", "proyeccion_24_72h", "situacion",
                      "personal", "inteligencia", "operaciones", "logistica", "trazabilidad"}


# ---------------------------------------------------------------------------
#  Catálogo de modelos del servicio
# ---------------------------------------------------------------------------
def test_listar_modelos_quita_prefijo_y_ordena(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _Router(_por_seccion()))
    assert listar_modelos(_aj()) == ["a-modelo", "b-modelo"]


def test_listar_modelos_error_legible(monkeypatch):
    def roto(**kw):
        raise RuntimeError("404 Not Found")
    monkeypatch.setattr(openai, "OpenAI", roto)
    with pytest.raises(LLMError, match="lista de modelos"):
        listar_modelos(_aj())


# ---------------------------------------------------------------------------
#  Verificación con el parte ficticio
# ---------------------------------------------------------------------------
def _verificar(monkeypatch, resp):
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _Router(resp))
    avances = []
    r = verificar_modelo(_aj(), avances.append)
    return r, avances


def test_verificacion_compatible(monkeypatch):
    r, avances = _verificar(monkeypatch, _por_seccion())
    assert r["veredicto"] == "COMPATIBLE"
    assert [p["estado"] for p in r["pasos"]] == ["ok"] * 4
    assert [a["paso_actual"] for a in avances] == [1, 2, 3, 4]


def test_verificacion_con_cifra_equivocada(monkeypatch):
    malo = {"personal": {"parte_fuerza_institucional": {"total": "1.420"}}}
    r, _ = _verificar(monkeypatch, _por_seccion({"SOLO la sección PERSONAL": (json.dumps(malo), "stop")}))
    assert r["veredicto"] == "COMPATIBLE_CON_OBSERVACIONES"
    assert r["pasos"][-1]["estado"] == "advertencia" and "1240" in r["pasos"][-1]["detalle"]


def test_verificacion_no_compatible_si_no_extrae(monkeypatch):
    def resp(system, user):
        if "Extrae los hechos" in system:
            return '{"hechos": []}', "stop"
        return _por_seccion()(system, user)
    r, _ = _verificar(monkeypatch, resp)
    assert r["veredicto"] == "NO_COMPATIBLE" and len(r["pasos"]) == 2


def test_verificacion_recomienda_secciones_con_ventana_chica(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _Router(_por_seccion()))
    r = verificar_modelo(_aj(context_tokens=8192))
    assert r["modo_sintesis_recomendado"] == "secciones"


# ---------------------------------------------------------------------------
#  Tareas en segundo plano: la clave no viaja en claro por Redis
# ---------------------------------------------------------------------------
def test_paquete_cifrado_ida_y_vuelta():
    aj = _aj(api_key="clave-super-secreta-123")
    paquete = aj_mod.empaquetar(aj)
    assert "clave-super-secreta" not in paquete
    assert aj_mod.desempaquetar(paquete) == aj


# ---------------------------------------------------------------------------
#  Gateway LiteLLM y Ollama
# ---------------------------------------------------------------------------
def test_preset_litellm_usa_la_clave_maestra(monkeypatch):
    monkeypatch.setattr(settings, "litellm_master_key", "sk-maestra")
    p = catalogo.presets()["litellm"]
    assert p.base_url == "http://litellm:4000/v1" and p.api_key == "sk-maestra" and p.resguardo == "ALTO"
    aj = construir("litellm", {"modelo": "claude-bedrock"}, origen="env")
    assert aj.adaptador == "openai" and aj.modelo == "claude-bedrock"


def test_raiz_de_ollama():
    assert ollama.raiz("http://host:11434/v1") == "http://host:11434"
    assert ollama.raiz("http://host:11434/v1/") == "http://host:11434"
    with pytest.raises(LLMError):
        ollama.raiz("host:11434")


# ---------------------------------------------------------------------------
#  API
# ---------------------------------------------------------------------------
client = TestClient(app)


def _h(*roles):
    t = crear_token(sub="u", uid="00000000-0000-0000-0000-000000000001", nivel="SECRETO",
                    roles=list(roles), unidad="TI")
    return {"Authorization": f"Bearer {t}"}


ADMIN = _h("Administrador del Sistema")


def test_api_modelos(monkeypatch):
    from app.api import llm as api_llm

    monkeypatch.setattr(api_llm, "listar_modelos", lambda aj: ["qwen3.8:27b", "gpt-oss:20b"])
    monkeypatch.setattr(api_llm.ollama, "version", lambda url: "0.40")
    r = client.post("/llm/modelos", headers=ADMIN, json={"proveedor": "local"})
    assert r.status_code == 200 and r.json() == {"modelos": ["qwen3.8:27b", "gpt-oss:20b"], "ollama": True}
    assert client.post("/llm/modelos", headers=_h("Auditor"), json={"proveedor": "local"}).status_code == 403


def test_api_descargar_solo_local():
    r = client.post("/llm/descargar", headers=ADMIN, json={"proveedor": "openai", "modelo": "x"})
    assert r.status_code == 400


def test_api_verificar_y_seguir_tarea(monkeypatch):
    from app import worker

    lanzado = {}
    monkeypatch.setattr(worker.llm_verificar, "delay",
                        lambda paquete, actor: lanzado.update(p=paquete) or SimpleNamespace(id="t-1"))
    r = client.post("/llm/verificar", headers=ADMIN, json={"proveedor": "local", "modelo": "qwen3.8:27b"})
    assert r.status_code == 200 and r.json() == {"tarea": "t-1", "modelo": "local/qwen3.8:27b"}
    assert aj_mod.desempaquetar(lanzado["p"]).modelo == "qwen3.8:27b"

    estados = {
        "SUCCESS": SimpleNamespace(state="SUCCESS", result={"veredicto": "COMPATIBLE"}),
        "PROGRESS": SimpleNamespace(state="PROGRESS", info={"paso_actual": 2}),
        "FAILURE": SimpleNamespace(state="FAILURE", result=RuntimeError("caído")),
    }
    for estado, esperado in [("SUCCESS", "OK"), ("PROGRESS", "EN_CURSO"), ("FAILURE", "ERROR")]:
        monkeypatch.setattr(worker.celery_app, "AsyncResult", lambda i, e=estado: estados[e])
        assert client.get("/llm/tareas/t-1", headers=ADMIN).json()["estado"] == esperado
