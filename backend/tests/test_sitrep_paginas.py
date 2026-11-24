"""Contenido del SITREP: elegir qué páginas de la plantilla entran (Motor de IA)."""
from __future__ import annotations

import copy
import io
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation

from app import sitrep_paginas as sp
from app.auth.tokens import crear_token
from app.llm.provider import crear_proveedor
from app.main import app
from app.pipeline import reporte_pptx
from tests.test_llm_cualquier_modelo import SECCION_OK, _aj, _por_seccion, _Router  # noqa: F401

CONTENIDO = {
    "resumen_ejecutivo": ["a"], "situacion": {"resumen": "s"},
    "personal": {"slc": {"total": "21"}},
    "inteligencia": {"analisis_meteo": "lluvia"},
    "operaciones": {"ops_catastrofe": [{"tipo": "incendio"}], "despliegue_mapa": {"mzn": "3"}},
    "logistica": {"resumen": {"total": "10"}},
    "trazabilidad": {"resumen_ejecutivo[0]": ["h1"], "logistica.resumen.total": ["h2"],
                     "operaciones.ops_catastrofe[0]": ["h3"], "operaciones.despliegue_mapa.mzn": ["h4"]},
}


def test_normalizar_valida_y_protege_la_portada():
    assert sp.normalizar(["logistica", "personal"]) == ["personal", "logistica"]  # orden de la plantilla
    with pytest.raises(sp.PaginasError, match="obligatoria"):
        sp.normalizar(["ejecutivo"])
    with pytest.raises(sp.PaginasError, match="desconocida"):
        sp.normalizar(["otra"])


def test_quitar_vacia_datos_y_trazabilidad_y_lo_anota():
    c = sp.quitar(copy.deepcopy(CONTENIDO), ["logistica", "operaciones_despliegue"])
    assert c["logistica"] == {}
    assert c["operaciones"] == {"despliegue_mapa": {"mzn": "3"}}  # la otra página de operaciones queda
    assert set(c["trazabilidad"]) == {"resumen_ejecutivo[0]", "operaciones.despliegue_mapa.mzn"}
    assert c["generacion"]["paginas_excluidas"] == ["operaciones_despliegue", "logistica"]
    assert sp.quitar(copy.deepcopy(CONTENIDO), []) == CONTENIDO


def test_por_secciones_no_pide_las_paginas_quitadas():
    cli = _Router(_por_seccion())
    p = crear_proveedor(_aj(sintesis_modo="secciones"), cli)
    out = p.sintetizar_briefing([], {"paginas_excluidas": ["logistica", "inteligencia"]})
    assert len(cli.sistemas) == 4
    assert not any("LOGÍSTICA" in s or "INTELIGENCIA" in s for s in cli.sistemas)
    assert out["logistica"] == {} and out["personal"]
    assert not any("paginas_excluidas" in s for s in cli.sistemas)


def test_completa_recibe_la_instruccion_y_no_el_parametro():
    completa = {**SECCION_OK["RESUMEN EJECUTIVO"], "logistica": {"resumen": {"total": "9"}}}
    vistos = []

    def resp(system, user):
        vistos.append(user)
        return json.dumps(completa), "stop"

    cli = _Router(resp)
    crear_proveedor(_aj(sintesis_modo="completa"), cli).sintetizar_briefing([], {"paginas_excluidas": ["logistica"]})
    assert "NO las redactes" in cli.sistemas[0] and "Logística" in cli.sistemas[0]
    assert "paginas_excluidas" not in vistos[0]


def test_pdf_saca_las_paginas_quitadas_y_conserva_las_hojas():
    c = copy.deepcopy(CONTENIDO)
    c["hojas_adicionales"] = [{"id": "x", "titulo": "Extra", "despues_de": 5,
                               "bloques": [{"tipo": "texto", "texto": "hola"}]}]
    completo = len(Presentation(io.BytesIO(reporte_pptx.construir_pptx(c, datetime(2026, 11, 24)))).slides)
    sp.quitar(c, ["inteligencia", "logistica"])
    prs = Presentation(io.BytesIO(reporte_pptx.construir_pptx(c, datetime(2026, 11, 24))))
    assert len(prs.slides) == completo - 2
    textos = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    assert "EXTRA" in textos.upper()


def _token(*roles):
    t = crear_token(sub="u", uid="00000000-0000-0000-0000-000000000001", nivel="SECRETO",
                    roles=list(roles), unidad="TI")
    return {"Authorization": f"Bearer {t}"}


def test_api_permisos_y_sin_migracion(monkeypatch):
    monkeypatch.setattr(sp, "leer", lambda db: {"excluidas": [], "migracion_aplicada": False, "actualizado_en": None})
    client = TestClient(app)
    r = client.get("/llm/sitrep-paginas", headers=_token("Auditor"))
    assert r.status_code == 200
    d = r.json()
    assert [p["numero"] for p in d["paginas"]] == [1, 2, 3, 4, 5, 6] and not d["puede_editar"]
    assert client.get("/llm/sitrep-paginas", headers=_token("Oficial de Operaciones")).status_code == 403
    assert client.put("/llm/sitrep-paginas", headers=_token("Auditor"), json={"excluidas": []}).status_code == 403
    r = client.put("/llm/sitrep-paginas", headers=_token("Administrador del Sistema"), json={"excluidas": ["logistica"]})
    assert r.status_code == 409 and "004" in r.text
