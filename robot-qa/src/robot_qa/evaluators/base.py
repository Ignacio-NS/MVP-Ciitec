"""Contrato de Evaluator (Guia S4 y S5): evaluate(input, output, context) -> Score.

Un evaluador puede ser puramente determinista (no toca red) o pedir recursos
adicionales via EvaluatorContext: el propio SutAdapter (para el evaluador
metamorfico, que necesita ejecutar una segunda variante), el ground truth
sintetico, y un "juez" LLM opcional para la rubrica semantica.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from ..models import Observation, Score, TestCase


@dataclass
class EvaluatorContext:
    run_id: str
    adapter: Any = None  # SutAdapter, solo si el evaluador lo necesita (p.ej. metamorphic)
    ground_truth: dict = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    judge: Callable[[str, dict], dict] | None = None  # prompt_id, variables -> {"score":..,"reason":..}
    evidence_dir: Path | None = None
    sibling_scores: list = field(default_factory=list)  # Scores ya calculados para esta misma Observation


class Evaluator(Protocol):
    id: str

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        ...
