"""Pantalla "Pruebas QA": lectura de los resultados de benchmark_llm (solo lectura)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import qa_resultados as qa
from app.auth.tokens import crear_token
from app.config import settings
from app.main import app

client = TestClient(app)


def _h(*roles):
    t = crear_token(sub="u", uid="00000000-0000-0000-0000-000000000001", nivel="SECRETO",
                    roles=list(roles), unidad="TI")
    return {"Authorization": f"Bearer {t}"}


def _corrida(etiqueta, modelo, n, tiempo, sitrep, inicio="2026-11-23T01:34:32+00:00"):
    return {
        "etiqueta": etiqueta, "proveedor": modelo.split("-")[0], "modelo": modelo, "corrida": n,
        "inicio": inicio, "sitrep_ok": True, "tiempo_total_s": tiempo,
        "tokens_in": 16000, "tokens_out": 9500, "llamadas": 9,
        "fases": {"extraccion": {"tiempo_s": 8, "hechos_por_doc": {"a.xlsx": 0, "b.txt": 3}},
                  "contradicciones": {"tiempo_s": 2}, "sintesis": {"tiempo_s": 12}},
        "calidad": {"aciertos": 39, "total": 40, "pct": 97.5, "por_seccion": {"PERSONAL": "10/11"},
                    "detalle": [{"seccion": "PERSONAL", "dato": "OF 2840", "ok": True}]},
        "sitrep": sitrep, "hechos": [{"id": "h0", "evento": "x", "fuente": "b.txt"}],
        "contradicciones": [{"descripcion": "c", "hechos_involucrados": ["h0"]}],
    }


@pytest.fixture()
def carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "qa_resultados_dir", str(tmp_path))
    (tmp_path / "documentos.json").write_text(json.dumps(
        {"b.txt": {"texto": "Fuerza total 43720 efectivos; 1.500 en catástrofe; 80 evacuados"}}))
    sit = {"resumen_ejecutivo": ["Fuerza de 43.720 efectivos", "1500 disponibles", "999 inventados"],
           "trazabilidad": {"resumen_ejecutivo[0]": ["h0"]}, "generacion": {"modo": "completa", "avisos": []}}
    for n, t in ((1, 20.0), (2, 30.0)):
        (tmp_path / f"deepseek-chat-qa-nov__corrida{n}.json").write_text(
            json.dumps(_corrida("DeepSeek chat (config actual) [QA nov]", "deepseek-chat", n, t, sit)))
    (tmp_path / "resumen.jsonl").write_text(json.dumps(
        {"etiqueta": "Groq gpt-oss-20b [QA nov]", "proveedor": "groq", "modelo": "openai/gpt-oss-20b",
         "estado": "NO_DISPONIBLE", "error": "401 Invalid API Key"}) + "\n")
    (tmp_path / "otro.txt").write_text("no es una corrida")
    return tmp_path


def test_listar_agrupa_por_lote_y_motor(carpeta):
    r = qa.listar()
    assert r["disponible"] and r["lotes"] == ["QA nov"]
    assert len(r["corridas"]) == 2
    (g,) = r["resumen"]
    assert g["motor"] == "DeepSeek chat" and g["exitosas"] == 2
    assert g["tiempo_s"] == 25.0 and g["tiempo_min_s"] == 20.0 and g["tiempo_max_s"] == 30.0
    # 16000 × 0,30 + 9500 × 1,20 = 0,0162 US$ → ≈ 15,9 CLP
    assert g["costo_clp"] == 15.9
    assert r["no_disponibles"][0]["motor"] == "Groq gpt-oss-20b"


def test_exactitud_marca_cifras_que_no_estan_en_las_fuentes(carpeta):
    d = qa.detalle("deepseek-chat-qa-nov__corrida1")
    ex = d["exactitud_detalle"]
    assert ex["cifras"] == 3 and ex["no_encontradas"] == ["999"]
    assert ex["pct"] == pytest.approx(66.7)
    assert d["hechos_por_doc"] == {"a.xlsx": 0, "b.txt": 3}


def test_ids_invalidos_no_leen_archivos(carpeta):
    for malo in ("../secreto", "documentos", "x__corrida1/../../etc", "DeepSeek__corrida1"):
        assert qa.detalle(malo) is None


def test_lote_sin_corchetes_es_el_benchmark_del_mes():
    assert qa._lote_y_nombre("Gemini 2.5 Flash (respetando cuota)", "2026-10-19T02:00:00") == \
        ("Benchmark oct-2026", "Gemini 2.5 Flash")


def test_sin_carpeta_no_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "qa_resultados_dir", str(tmp_path / "no-existe"))
    assert qa.listar()["disponible"] is False


def test_api_permisos_y_404(carpeta):
    assert client.get("/qa/corridas", headers=_h("Administrador del Sistema")).status_code == 200
    assert client.get("/qa/corridas", headers=_h("Auditor")).status_code == 200
    assert client.get("/qa/corridas", headers=_h("Oficial de Operaciones")).status_code == 403
    r = client.get("/qa/corridas/deepseek-chat-qa-nov__corrida2", headers=_h("Auditor"))
    assert r.status_code == 200 and r.json()["sitrep"]["resumen_ejecutivo"][0].startswith("Fuerza")
    assert client.get("/qa/corridas/nada__corrida9", headers=_h("Auditor")).status_code == 404


def test_exportar_usa_el_exportador_institucional(carpeta, monkeypatch):
    from app.api import qa as api_qa

    llamadas = []

    def falso(contenido, formato, titulo, fecha):
        llamadas.append((contenido["resumen_ejecutivo"][0], formato, titulo, fecha.year))
        return b"%PDF-falso", "application/pdf", "pdf"

    monkeypatch.setattr(api_qa.exportacion, "render", falso)
    r = client.post("/qa/corridas/deepseek-chat-qa-nov__corrida1/exportar", json={"formato": "PDF"},
                    headers=_h("Auditor"))
    assert r.status_code == 200 and r.content == b"%PDF-falso"
    assert 'QA_deepseek-chat-qa-nov__corrida1.pdf' in r.headers["content-disposition"]
    assert llamadas == [("Fuerza de 43.720 efectivos", "PDF", "SITREP de prueba - DeepSeek chat - corrida 1", 2026)]


def test_exportar_texto_real_y_permisos(carpeta):
    r = client.post("/qa/corridas/deepseek-chat-qa-nov__corrida2/exportar", json={"formato": "TEXTO"},
                    headers=_h("Administrador del Sistema"))
    assert r.status_code == 200 and "Fuerza de 43.720 efectivos" in r.text
    assert client.post("/qa/corridas/deepseek-chat-qa-nov__corrida2/exportar", json={"formato": "PDF"},
                       headers=_h("Oficial de Operaciones")).status_code == 403
    assert client.post("/qa/corridas/nada__corrida1/exportar", json={"formato": "PDF"},
                       headers=_h("Auditor")).status_code == 404


def test_exactitud_acepta_miles_con_coma(carpeta):
    # gpt-oss-120b escribe 1,440 (estilo inglés) para la cifra 1.440 / 1440 de los documentos
    from app.qa_resultados import _formas

    assert "1440" in _formas("1,440")
    assert "1440" in _formas("1.440")
    assert "2.5" in _formas("2,5")  # decimal con coma se mantiene
