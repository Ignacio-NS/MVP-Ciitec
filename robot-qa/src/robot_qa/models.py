"""Contratos de datos del robot QA.

Los campos de TestCase siguen literalmente el formato de caso de prueba de la
Guia del proyecto (S6): case_id, requirement_id, category, input, setup,
expected, evaluators, thresholds, repetitions, severity, tags.

Observation es lo que produce el "Capturador" (S4, paso 4): salida, trazas,
fuentes, latencia, tokens y costo. Score es lo que produce cada "Evaluador"
(S4, paso 5). CaseResult agrega las repeticiones de un caso; CampaignResult
agrega todos los casos y aplica el gate de liberacion (S11).
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Verdict(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    ERROR = "ERROR"


class Gate(str, enum.Enum):
    PASS = "PASS"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    REJECT = "REJECT"


# ---------------------------------------------------------------- Test case
class TestCase(BaseModel):
    """Un caso de prueba versionado (Guia S6)."""

    model_config = ConfigDict(extra="allow")

    case_id: str
    requirement_id: str
    category: str
    title: str = ""
    description: str = ""
    input: dict = Field(default_factory=dict)
    setup: dict = Field(default_factory=dict)
    expected: dict = Field(default_factory=dict)
    evaluators: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    repetitions: int = 1
    severity: str = "medium"  # low | medium | high | critical
    tags: list[str] = Field(default_factory=list)
    source_file: str = ""  # ruta del YAML de origen, para trazabilidad


# ----------------------------------------------------------------- Captura
class Observation(BaseModel):
    """Lo que devuelve el SUT Adapter para una repeticion de un caso."""

    model_config = ConfigDict(extra="allow")

    case_id: str
    repetition: int
    run_id: str
    output: dict = Field(default_factory=dict)
    raw_text: str = ""
    traces: dict = Field(default_factory=dict)
    sources_used: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    http_status: int | None = None
    sut_version: str = ""
    error: str | None = None
    captured_at: str = Field(default_factory=_now_iso)


# --------------------------------------------------------------- Evaluacion
class Score(BaseModel):
    """Lo que devuelve un Evaluator para una Observation."""

    model_config = ConfigDict(extra="allow")

    evaluator_id: str
    case_id: str
    repetition: int
    value: float  # metrica normalizada 0..1 salvo que el evaluador documente otra escala
    passed: bool
    critical: bool = False  # si True y passed=False, fuerza REJECT en el gate
    detail: str = ""
    evidence_ref: str | None = None


class CaseResult(BaseModel):
    """Agregado de todas las repeticiones y evaluadores de un caso."""

    model_config = ConfigDict(extra="allow")

    case: TestCase
    observations: list[Observation] = Field(default_factory=list)
    scores: list[Score] = Field(default_factory=list)
    verdict: Verdict = Verdict.ERROR
    consistency: float | None = None  # acuerdo entre repeticiones (pass@k / varianza)
    notes: str = ""


class CampaignResult(BaseModel):
    """Resultado completo de una campana: todos los CaseResult + metricas + gate."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    campaign: str
    started_at: str
    finished_at: str = ""
    cases: list[CaseResult] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    gate: Gate = Gate.HUMAN_REVIEW
    gate_reason: str = ""
    manifest: dict = Field(default_factory=dict)
