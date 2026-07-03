"""
Filtro 4 — DETECCIÓN DE INCONSISTENCIAS (RF-005):

- DUPLICADO    : similitud coseno de embeddings via pgvector (umbral configurable).
                 Los casi-idénticos se AGRUPAN en clústeres (union-find): un dato
                 corroborado por N fuentes es UNA inconsistencia, no N·(N-1)/2 pares.
- CONTRADICCION: el LLM compara los hechos entre sí.
- DESACTUALIZADO: hechos cuya fecha supera el umbral de antigüedad.
- INCOMPLETO   : hechos con campos clave faltantes.

`detectar` devuelve (inconsistencias, hechos_sin_duplicados): las primeras se
persisten como filas de `inconsistencias`; la segunda lista alimenta la síntesis
ya deduplicada (un representante por clúster).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..llm.provider import LLMProvider, LLMError
from ..models import Hecho


def _clusters_duplicados(db: Session, hechos: list[Hecho]) -> list[list[str]]:
    """Agrupa hechos casi idénticos en clústeres (componentes conexas del grafo de
    similitud coseno ≥ umbral) con union-find. Así, un mismo dato corroborado por
    varias fuentes queda en UN clúster en lugar de generar un par por combinación.
    """
    umbral = settings.dedup_threshold
    ids = [str(h.id) for h in hechos]
    if len(ids) < 2:
        return []

    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # compresión de camino
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Vecinos sobre el umbral por hecho, vía índice HNSW (operador <=> = distancia coseno).
    sql = text(
        """
        SELECT h2.id AS otro
        FROM hechos h1
        JOIN hechos h2 ON h2.id <> h1.id AND h2.id = ANY(:ids)
        WHERE h1.id = :hid AND h1.embedding IS NOT NULL AND h2.embedding IS NOT NULL
          AND 1 - (h1.embedding <=> h2.embedding) >= :umbral
        ORDER BY h1.embedding <=> h2.embedding
        LIMIT :k
        """
    )
    for h in hechos:
        if h.embedding is None:
            continue
        for fila in db.execute(sql, {"hid": str(h.id), "ids": ids, "umbral": umbral, "k": 25}):
            union(str(h.id), str(fila.otro))

    grupos: dict[str, list[str]] = {}
    for i in ids:
        grupos.setdefault(find(i), []).append(i)
    return [g for g in grupos.values() if len(g) > 1]


def _inconsistencias_duplicado(clusters: list[list[str]], por_id: dict[str, Hecho]) -> list[dict[str, Any]]:
    """Una sola inconsistencia DUPLICADO por clúster (no por par)."""
    out: list[dict[str, Any]] = []
    for g in clusters:
        fuentes = {str(por_id[i].fuente_id) for i in g if i in por_id}
        out.append(
            {
                "tipo": "DUPLICADO",
                "severidad": 2,
                "descripcion": (
                    f"{len(g)} hechos equivalentes corroborados por {len(fuentes)} "
                    f"fuente(s); se conserva uno como representativo."
                ),
                "hechos_involucrados": g,
            }
        )
    return out


def _riqueza(h: Hecho) -> tuple[int, float]:
    """Completitud del hecho (campos con dato) y luego confianza: elige el
    representante del clúster (el más informativo)."""
    campos = sum(1 for v in (h.ubicacion, h.responsable, h.ocurrido_en, h.impacto) if v)
    return (campos, h.confianza or 0.0)


def _deduplicar(hechos: list[Hecho], clusters: list[list[str]]) -> list[Hecho]:
    """Colapsa cada clúster a su hecho más completo y conserva los no agrupados.
    El resultado alimenta la síntesis para que el LLM no reciba copias casi idénticas.
    """
    por_id = {str(h.id): h for h in hechos}
    en_cluster = {i for g in clusters for i in g}
    representantes = [
        max((por_id[i] for i in g if i in por_id), key=_riqueza) for g in clusters
    ]
    resto = [h for h in hechos if str(h.id) not in en_cluster]
    return representantes + resto


def _desactualizados(hechos: list[Hecho]) -> list[dict[str, Any]]:
    # Referencia = fecha del hecho MÁS RECIENTE del lote (no el reloj del servidor).
    # Un parte del 22-06 revisado el 01-07 no está "viejo": solo lo está un hecho
    # anterior en más de `desactualizado_dias` al más reciente del propio lote.
    fechas = [h.ocurrido_en for h in hechos if h.ocurrido_en]
    if not fechas:
        return []
    referencia = max(fechas)
    limite = referencia - timedelta(days=settings.desactualizado_dias)
    out = []
    for h in hechos:
        if h.ocurrido_en and h.ocurrido_en < limite:
            out.append(
                {
                    "tipo": "DESACTUALIZADO",
                    "severidad": 1,
                    "descripcion": (
                        f"Hecho con fecha {h.ocurrido_en.date()} anterior en más de "
                        f"{settings.desactualizado_dias} días al parte más reciente del "
                        f"lote ({referencia.date()})."
                    ),
                    "hechos_involucrados": [str(h.id)],
                }
            )
    return out


def _incompletos(hechos: list[Hecho]) -> list[dict[str, Any]]:
    # Un hecho es "suficientemente completo" si tiene el evento (qué pasó) y al menos
    # un ancla: fecha O ubicación. Solo se marca lo genuinamente vago (p.ej. "hubo un
    # incidente" sin cuándo ni dónde). Antes se exigían los 3 campos (ubicación,
    # responsable y fecha) y casi todo hecho de tabla/cifra caía como incompleto.
    out = []
    for h in hechos:
        if h.evento and (h.ocurrido_en or h.ubicacion):
            continue
        motivo = "sin descripción del evento" if not h.evento else "sin fecha ni ubicación"
        out.append(
            {
                "tipo": "INCOMPLETO",
                "severidad": 1,
                "descripcion": f"Hecho {motivo}.",
                "hechos_involucrados": [str(h.id)],
            }
        )
    return out


def _contradicciones(hechos: list[Hecho], provider: LLMProvider) -> list[dict[str, Any]]:
    payload = [
        {
            "id": str(h.id),
            "evento": h.evento,
            "ocurrido_en": h.ocurrido_en.isoformat() if h.ocurrido_en else "",
            "ubicacion": h.ubicacion or "",
            "responsable": h.responsable or "",
            "estado": h.estado or "",
        }
        for h in hechos
    ]
    try:
        crudas = provider.detectar_contradicciones(payload)
    except LLMError:
        return []
    return [
        {
            "tipo": "CONTRADICCION",
            "severidad": int(c.get("severidad", 2)),
            "descripcion": c.get("descripcion", "Contradicción detectada."),
            "hechos_involucrados": c.get("hechos_involucrados", []),
        }
        for c in crudas
    ]


def detectar(
    db: Session, hechos: list[Hecho], provider: LLMProvider
) -> tuple[list[dict[str, Any]], list[Hecho]]:
    """Corre las cuatro detecciones.

    Devuelve (inconsistencias, hechos_sin_duplicados): los casi-duplicados se
    agrupan en clústeres (una inconsistencia por clúster) y se entrega además la
    lista deduplicada —un representante por clúster— para alimentar la síntesis.
    """
    clusters = _clusters_duplicados(db, hechos)
    por_id = {str(h.id): h for h in hechos}
    inconsistencias = (
        _inconsistencias_duplicado(clusters, por_id)
        + _contradicciones(hechos, provider)
        + _desactualizados(hechos)
        + _incompletos(hechos)
    )
    hechos_unicos = _deduplicar(hechos, clusters)
    return inconsistencias, hechos_unicos
