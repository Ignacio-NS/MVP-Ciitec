"""
Router del motor de IA: ver y cambiar el proveedor/modelo desde la interfaz.

- Ver (Administrador, Auditor, Oficial de Seguridad): configuración efectiva,
  catálogo de proveedores e historial. Nunca se devuelve una API key.
- Cambiar (solo Administrador del Sistema, y solo si LLM_CONFIG_UI=true):
  activar una configuración nueva o volver al .env. Cada cambio queda en el
  audit_log (acción CONFIG_IA) y en la tabla append-only `llm_config`.
- /info (cualquier usuario autenticado): proveedor y modelo activos, para que
  el Robot QA registre en su manifiesto con qué IA corrió cada campaña.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from .. import audit
from ..auth import rbac
from ..auth.deps import CurrentUser, get_current_user, require_roles
from ..config import settings
from ..db import get_db
from ..llm import ajustes as ajustes_mod
from ..llm import catalogo
from ..llm.ajustes import ConfigIAError
from ..llm import ollama
from ..llm.provider import LLMError, listar_modelos, probar_conexion
from ..models import LLMConfig, Usuario
from ..schemas.api import LLMConfigIn

router = APIRouter(prefix="/llm", tags=["motor-ia"])
info_router = APIRouter(tags=["motor-ia"])

_ver = require_roles(*rbac.ROLES_VER_CONFIG_IA)
_editar = require_roles(*rbac.ROLES_CONFIG_IA)


def _vigente(db: Session) -> LLMConfig | None:
    return db.execute(select(LLMConfig).where(LLMConfig.vigente.is_(True))).scalar_one_or_none()


def _migracion_aplicada(db: Session) -> bool:
    try:
        _vigente(db)
        return True
    except Exception:  # noqa: BLE001 — tabla llm_config inexistente
        db.rollback()
        return False


def _exigir_ui_habilitada() -> None:
    if not settings.llm_config_ui:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "El cambio de motor de IA desde la interfaz está deshabilitado en este servidor "
            "(LLM_CONFIG_UI=false). Debe hacerse en el .env.",
        )


def _fila_desde(body: LLMConfigIn, api_key: str | None) -> SimpleNamespace:
    """Objeto con la forma de una fila de llm_config, para validar sin guardar."""
    return SimpleNamespace(
        proveedor=(body.proveedor or "").strip().lower(),
        modelo=(body.modelo or "").strip() or None,
        base_url=(body.base_url or "").strip() or None,
        api_key=api_key,
        json_mode=body.json_mode,
        temperature=(body.temperature or "").strip() or None,
        token_param=(body.token_param or "").strip() or None,
        extra_params=body.extra_params if body.extra_params else None,
        context_tokens=body.context_tokens or None,
        timeout_s=body.timeout_s or None,
        sintesis_modo=(body.sintesis_modo or "").strip().lower() or None,
    )


def _clave_para(db: Session, body: LLMConfigIn) -> str | None:
    """Resuelve la API key según la convención de LLMConfigIn (None conserva, '' borra)."""
    if body.api_key is None:
        try:
            actual = _vigente(db)
        except Exception:  # noqa: BLE001 — migración 003 no aplicada
            db.rollback()
            actual = None
        if actual is not None and actual.proveedor == body.proveedor.strip().lower():
            return actual.api_key
        return None
    return body.api_key.strip() or None


def _validar(body: LLMConfigIn, api_key: str | None):
    proveedor = (body.proveedor or "").strip().lower()
    if proveedor not in catalogo.nombres():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Proveedor de IA desconocido: '{proveedor}'. Valores válidos: {', '.join(catalogo.nombres())}",
        )
    if proveedor not in ajustes_mod.permitidos():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El proveedor '{proveedor}' no está permitido en este servidor. "
            f"Permitidos: {', '.join(sorted(ajustes_mod.permitidos()))}",
        )
    fila = _fila_desde(body, api_key)
    try:
        return fila, ajustes_mod.desde_fila(fila)
    except ConfigIAError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


# ---------------------------------------------------------------------------
#  Lectura
# ---------------------------------------------------------------------------
@router.get("/proveedores")
def proveedores(user: CurrentUser = Depends(_ver)):
    """Catálogo de proveedores con sus valores por defecto (sin claves)."""
    perm = ajustes_mod.permitidos()
    out = []
    for p in catalogo.presets().values():
        out.append({
            "nombre": p.nombre, "etiqueta": p.etiqueta, "adaptador": p.adaptador,
            "resguardo": p.resguardo, "descripcion": p.descripcion,
            "base_url": p.base_url, "modelo": p.modelo,
            "requiere_api_key": p.requiere_api_key,
            "clave_en_servidor": bool(p.api_key),
            "json_mode": p.json_mode, "temperature": p.temperature,
            "token_param": p.token_param,
            "extra_params": catalogo.extra_por_defecto(p, p.modelo),
            "permitido": p.nombre in perm,
        })
    return {"proveedores": out, "ui_habilitada": settings.llm_config_ui, "permitidos": sorted(perm)}


@router.get("/config")
def ver_config(user: CurrentUser = Depends(_ver), db: Session = Depends(get_db)):
    """Configuración efectiva (la que usará la próxima generación) y la del .env."""
    out: dict[str, Any] = {
        "ui_habilitada": settings.llm_config_ui,
        "puede_editar": rbac.tiene_rol(user.roles, rbac.ROLES_CONFIG_IA) and settings.llm_config_ui,
        "migracion_aplicada": _migracion_aplicada(db),
    }
    try:
        out["env"] = ajustes_mod.desde_env().publico()
    except ConfigIAError as e:
        out["env"] = None
        out["error_env"] = str(e)
    try:
        out["efectiva"] = ajustes_mod.resolver().publico()
    except ConfigIAError as e:
        out["efectiva"] = None
        out["error"] = str(e)
    return out


@router.get("/historial")
def historial(limit: int = 50, user: CurrentUser = Depends(_ver), db: Session = Depends(get_db)):
    if not _migracion_aplicada(db):
        return {"cambios": []}
    filas = db.execute(
        select(LLMConfig, Usuario.username)
        .join(Usuario, Usuario.id == LLMConfig.creado_por, isouter=True)
        .order_by(desc(LLMConfig.id))
        .limit(min(limit, 200))
    ).all()
    return {"cambios": [{
        "id": f.id, "proveedor": f.proveedor, "modelo": f.modelo, "base_url": f.base_url,
        "con_clave_propia": bool(f.api_key), "vigente": f.vigente,
        "creado_por": username, "creado_en": f.creado_en.isoformat() if f.creado_en else None,
        "desactivado_en": f.desactivado_en.isoformat() if f.desactivado_en else None,
    } for f, username in filas]}


# ---------------------------------------------------------------------------
#  Escritura (Administrador del Sistema)
# ---------------------------------------------------------------------------
@router.post("/probar")
def probar(body: LLMConfigIn | None = None, user: CurrentUser = Depends(_editar), db: Session = Depends(get_db)):
    """Prueba una configuración SIN guardarla (o la efectiva si no se envía cuerpo)."""
    if body is None:
        try:
            aj = ajustes_mod.resolver()
        except ConfigIAError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    else:
        _, aj = _validar(body, _clave_para(db, body))
    return probar_conexion(aj)


@router.put("/config")
def activar(body: LLMConfigIn, user: CurrentUser = Depends(_editar), db: Session = Depends(get_db)):
    """Activa un proveedor/modelo nuevo. Se aplica a la próxima generación, sin reiniciar."""
    _exigir_ui_habilitada()
    if not _migracion_aplicada(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Falta aplicar db/migrations/003_llm_configurable.sql para guardar la configuración.",
        )
    api_key = _clave_para(db, body)
    fila, aj = _validar(body, api_key)

    prueba = None
    if body.probar:
        prueba = probar_conexion(aj)
        if not prueba["ok"] and not body.forzar:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"La prueba de conexión falló; no se activó. Detalle: {prueba.get('error', 'respuesta inválida')}",
            )

    anterior = _vigente(db)
    firma_anterior = f"{anterior.proveedor}/{anterior.modelo}" if anterior else f"env:{settings.llm_provider}"
    db.execute(
        update(LLMConfig).where(LLMConfig.vigente.is_(True))
        .values(vigente=False, desactivado_en=datetime.now(timezone.utc))
    )
    nueva = LLMConfig(
        proveedor=fila.proveedor, modelo=fila.modelo, base_url=fila.base_url, api_key=api_key,
        json_mode=fila.json_mode, temperature=fila.temperature, token_param=fila.token_param,
        extra_params=fila.extra_params, context_tokens=fila.context_tokens, timeout_s=fila.timeout_s,
        sintesis_modo=fila.sintesis_modo,
        vigente=True, creado_por=user.id,
    )
    db.add(nueva)
    db.flush()
    audit.registrar(
        db, accion="CONFIG_IA", actor_id=user.id, entidad_tipo="llm_config", entidad_id=str(nueva.id),
        detalle={
            "cambio": "ACTIVAR", "anterior": firma_anterior, "nuevo": aj.firma(),
            "resguardo": aj.resguardo, "host": aj.publico()["host"],
            "clave_propia": bool(api_key), "prueba_ok": prueba["ok"] if prueba else None,
            "forzado": bool(body.forzar and prueba and not prueba["ok"]),
        },
        commit=False,
    )
    db.commit()
    ajustes_mod.invalidar_cache()
    return {"efectiva": aj.publico(), "prueba": prueba}


@router.delete("/config")
def volver_a_env(user: CurrentUser = Depends(_editar), db: Session = Depends(get_db)):
    """Desactiva la configuración de la interfaz: vuelve a mandar el .env del servidor."""
    _exigir_ui_habilitada()
    if not _migracion_aplicada(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Falta aplicar db/migrations/003_llm_configurable.sql.")
    anterior = _vigente(db)
    if anterior is None:
        return {"efectiva": ajustes_mod.desde_env().publico(), "sin_cambios": True}
    anterior.vigente = False
    anterior.desactivado_en = datetime.now(timezone.utc)
    try:
        env = ajustes_mod.desde_env()
    except ConfigIAError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"El .env del servidor no tiene una configuración válida: {e}")
    audit.registrar(
        db, accion="CONFIG_IA", actor_id=user.id, entidad_tipo="llm_config", entidad_id=str(anterior.id),
        detalle={"cambio": "VOLVER_A_ENV", "anterior": f"{anterior.proveedor}/{anterior.modelo}", "nuevo": env.firma()},
        commit=False,
    )
    db.commit()
    ajustes_mod.invalidar_cache()
    return {"efectiva": env.publico()}


# ---------------------------------------------------------------------------
#  Ver los modelos del servicio, verificarlos y (Ollama) descargarlos
# ---------------------------------------------------------------------------
def _ajustes_de(body: LLMConfigIn | None, db: Session):
    """Ajustes de la petición (o los efectivos si no hay cuerpo)."""
    if body is None:
        try:
            return ajustes_mod.resolver()
        except ConfigIAError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return _validar(body, _clave_para(db, body))[1]


@router.post("/modelos")
def modelos(body: LLMConfigIn, user: CurrentUser = Depends(_editar), db: Session = Depends(get_db)):
    """Lista los modelos que ofrece el servicio elegido (para elegir sin escribir el nombre).

    En Ollama son los ya descargados; para usar otro se puede descargar con /llm/descargar."""
    # Para listar no hace falta haber elegido modelo todavía.
    consulta = body.model_copy(update={"modelo": body.modelo or "-"})
    aj = _ajustes_de(consulta, db)
    es_ollama = aj.proveedor == "local" and ollama.version(aj.base_url) is not None
    try:
        lista = listar_modelos(aj)
    except LLMError as e:
        return {"modelos": [], "error": str(e), "ollama": es_ollama}
    return {"modelos": lista, "ollama": es_ollama}


def _lanzar(tarea, body: LLMConfigIn | None, user: CurrentUser, db: Session) -> dict[str, str]:
    aj = _ajustes_de(body, db)
    r = tarea.delay(ajustes_mod.empaquetar(aj), str(user.id))
    return {"tarea": r.id, "modelo": aj.firma()}


@router.post("/verificar")
def verificar(body: LLMConfigIn | None = None, user: CurrentUser = Depends(_editar), db: Session = Depends(get_db)):
    """Verifica en segundo plano si el modelo sirve para generar el SITREP (ver /llm/tareas/{id})."""
    from ..worker import llm_verificar

    return _lanzar(llm_verificar, body, user, db)


@router.post("/descargar")
def descargar(body: LLMConfigIn, user: CurrentUser = Depends(_editar), db: Session = Depends(get_db)):
    """Pide al servidor Ollama de la red institucional que descargue un modelo."""
    _exigir_ui_habilitada()
    if (body.proveedor or "").strip().lower() != "local":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Solo se pueden descargar modelos en el servidor local (Ollama).")
    if not (body.modelo or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Indique el modelo a descargar (p.ej. qwen3.8:27b).")
    from ..worker import llm_descargar

    return _lanzar(llm_descargar, body, user, db)


@router.get("/tareas/{tarea_id}")
def tarea(tarea_id: str, user: CurrentUser = Depends(_editar)):
    """Estado de una verificación o descarga: PENDIENTE | EN_CURSO | OK | ERROR."""
    from ..worker import celery_app

    r = celery_app.AsyncResult(tarea_id)
    if r.state == "SUCCESS":
        return {"estado": "OK", "resultado": r.result}
    if r.state == "FAILURE":
        return {"estado": "ERROR", "error": str(r.result)[:500]}
    if r.state == "PROGRESS":
        return {"estado": "EN_CURSO", "progreso": r.info}
    return {"estado": "EN_CURSO" if r.state == "STARTED" else "PENDIENTE"}


# ---------------------------------------------------------------------------
#  /info — proveedor activo para cualquier usuario autenticado (Robot QA)
# ---------------------------------------------------------------------------
@info_router.get("/info")
def info(user: CurrentUser = Depends(get_current_user)):
    try:
        aj = ajustes_mod.obtener()
    except ConfigIAError as e:
        return {"llm": None, "error": str(e)}
    return {"llm": {
        "proveedor": aj.proveedor, "modelo": aj.modelo, "firma": aj.firma(),
        "origen": aj.origen, "resguardo": aj.resguardo,
    }}
