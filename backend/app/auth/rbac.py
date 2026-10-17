"""
RBAC por rol, unidad y nivel de clasificación (RNF-001, RNF-002).

- Jerarquía de clasificación: PUBLICO < RESERVADO < SECRETO.
- Un usuario solo puede ver/descargar un recurso si su habilitación es >= a la
  clasificación del recurso.
"""
from __future__ import annotations

_ORDEN_NIVEL = {"PUBLICO": 0, "RESERVADO": 1, "SECRETO": 2}

# Roles con acceso al audit log (RNF-003).
ROLES_AUDITORIA = {"Auditor", "Oficial de Seguridad", "Administrador del Sistema"}
# Roles que pueden aprobar versiones de briefing (RF-007).
ROLES_APROBACION = {"Comandante", "Asesor de Operaciones", "Oficial de Operaciones"}
# Roles que pueden CAMBIAR el motor de IA desde la interfaz (proveedor/modelo/clave).
ROLES_CONFIG_IA = {"Administrador del Sistema"}
# Roles que pueden VER qué motor de IA está activo (sin claves).
ROLES_VER_CONFIG_IA = ROLES_CONFIG_IA | ROLES_AUDITORIA
# Roles que trascienden la unidad: ven recursos de cualquier unidad (RNF-001).
# El mando, la auditoría/seguridad y la administración no quedan segmentados por unidad.
ROLES_TRANSVERSAL = {"Comandante", "Auditor", "Oficial de Seguridad", "Administrador del Sistema"}


def nivel_ok(habilitacion: str, clasificacion: str) -> bool:
    """True si la habilitación del usuario alcanza la clasificación del recurso."""
    return _ORDEN_NIVEL.get(habilitacion, 0) >= _ORDEN_NIVEL.get(clasificacion, 99)


def tiene_rol(roles_usuario: list[str], roles_requeridos: set[str]) -> bool:
    return bool(set(roles_usuario) & roles_requeridos)


def es_transversal(roles_usuario: list[str]) -> bool:
    """True si el usuario puede acceder a recursos de cualquier unidad (RNF-001)."""
    return tiene_rol(roles_usuario, ROLES_TRANSVERSAL)


def unidad_ok(roles_usuario: list[str], unidad_usuario: str | None, unidad_recurso: str | None) -> bool:
    """
    True si el usuario puede acceder a un recurso según la segmentación por unidad
    (RNF-001). Reglas:
      - los roles transversales (mando/auditoría/admin) ven todo;
      - un recurso sin unidad asignada es accesible (compatibilidad/legado);
      - en el resto, la unidad del usuario debe coincidir con la del recurso.
    """
    if es_transversal(roles_usuario):
        return True
    if not unidad_recurso:
        return True
    return (unidad_usuario or "") == unidad_recurso
