"""API del motor de IA: permisos, bloqueo por servidor y que nunca se exponga una clave.

No requiere Postgres: sin BD, la configuración efectiva cae al .env (comportamiento esperado).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.tokens import crear_token
from app.config import settings
from app.llm import ajustes as aj_mod
from app.main import app

client = TestClient(app)


def _token(*roles: str) -> dict[str, str]:
    t = crear_token(sub="u", uid="00000000-0000-0000-0000-000000000001", nivel="SECRETO",
                    roles=list(roles), unidad="TI")
    return {"Authorization": f"Bearer {t}"}


ADMIN = ("Administrador del Sistema",)
AUDITOR = ("Auditor",)
OPERADOR = ("Oficial de Operaciones",)


@pytest.fixture(autouse=True)
def _sin_bd(monkeypatch):
    monkeypatch.setattr(aj_mod, "_leer_fila_vigente", lambda: None)
    monkeypatch.setattr(settings, "llm_provider", "local")
    aj_mod.invalidar_cache()
    yield
    aj_mod.invalidar_cache()


def test_catalogo_visible_para_admin_y_auditor_no_para_operador():
    assert client.get("/llm/proveedores", headers=_token(*ADMIN)).status_code == 200
    assert client.get("/llm/proveedores", headers=_token(*AUDITOR)).status_code == 200
    assert client.get("/llm/proveedores", headers=_token(*OPERADOR)).status_code == 403


def test_auditor_ve_pero_no_puede_cambiar():
    r = client.put("/llm/config", headers=_token(*AUDITOR), json={"proveedor": "local"})
    assert r.status_code == 403


def test_config_efectiva_sin_claves(monkeypatch):
    monkeypatch.setattr(settings, "local_llm_api_key", "clave-local-muy-secreta")
    r = client.get("/llm/config", headers=_token(*ADMIN))
    assert r.status_code == 200
    data = r.json()
    assert data["efectiva"]["proveedor"] == "local" and data["efectiva"]["origen"] == "env"
    assert "clave-local-muy-secreta" not in r.text


def test_bloqueo_desde_el_servidor(monkeypatch):
    monkeypatch.setattr(settings, "llm_config_ui", False)
    r = client.put("/llm/config", headers=_token(*ADMIN), json={"proveedor": "local"})
    assert r.status_code == 403 and "LLM_CONFIG_UI" in r.text


def test_info_para_cualquier_usuario_autenticado():
    r = client.get("/info", headers=_token(*OPERADOR))
    assert r.status_code == 200 and r.json()["llm"]["proveedor"] == "local"
    assert client.get("/info").status_code == 401
