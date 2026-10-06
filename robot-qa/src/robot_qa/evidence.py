"""Persistencia de evidencia (Guia S10): todo Observation queda en disco, sea
de un caso de la campana o de una variante metamorfica generada al vuelo, para
que `robot_qa run --replay <run_id>` pueda reconstruir una campana completa
sin volver a llamar al SUT ni al LLM.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import CaseResult, Observation, Score, TestCase


def save_observation(evidence_dir: Path, observation: Observation) -> None:
    obs_dir = evidence_dir / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    path = obs_dir / f"{observation.case_id}__rep{observation.repetition}.json"
    path.write_text(
        json.dumps(observation.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def load_observations(evidence_dir: Path) -> dict[tuple[str, int], Observation]:
    obs_dir = evidence_dir / "observations"
    out: dict[tuple[str, int], Observation] = {}
    if not obs_dir.is_dir():
        return out
    for f in obs_dir.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        obs = Observation.model_validate(data)
        out[(obs.case_id, obs.repetition)] = obs
    return out


def save_case(evidence_dir: Path, case: TestCase, observations: list[Observation], scores: list[Score]) -> None:
    cases_dir = evidence_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "case": case.model_dump(mode="json"),
        "observations": [o.model_dump(mode="json") for o in observations],
        "scores": [s.model_dump(mode="json") for s in scores],
    }
    (cases_dir / f"{case.case_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def save_manifest(evidence_dir: Path, manifest: dict) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
