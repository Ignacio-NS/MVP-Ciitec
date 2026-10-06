"""Adaptador de repeticion (`robot_qa run --replay <run_id>`, Guia S10).

Sirve Observations YA CAPTURADAS por una corrida anterior (incluidas las
variantes que genero el evaluador metamorfico al vuelo) sin llamar al SUT ni
al LLM. Permite reejecutar los evaluadores -- por ejemplo tras ajustar un
umbral o corregir un evaluador -- de forma barata y determinista, y demuestra
que la evidencia guardada alcanza para reconstruir la campana completa.
"""
from __future__ import annotations

from pathlib import Path

from ..evidence import load_observations
from ..models import Observation, TestCase


class ReplayAdapter:
    id = "replay"

    def __init__(self, source_evidence_dir: Path) -> None:
        self.source_evidence_dir = source_evidence_dir
        self._observations = load_observations(source_evidence_dir)
        if not self._observations:
            raise FileNotFoundError(
                f"no hay evidencia de observaciones en {source_evidence_dir}/observations/"
            )

    def close(self) -> None:
        pass

    def invoke(self, case: TestCase, *, repetition: int, run_id: str) -> Observation:
        key = (case.case_id, repetition)
        stored = self._observations.get(key)
        if stored is None:
            return Observation(
                case_id=case.case_id, repetition=repetition, run_id=run_id,
                error=f"replay: sin evidencia guardada para {key} en {self.source_evidence_dir}",
            )
        return stored
