"""Orquestador (Guia S4, paso 1 y S4 completo): ejecuta una campana de punta a punta.

Flujo por caso: Adaptador (captura Observation) -> Evaluadores (Score) ->
agregacion en CaseResult. El CampaignResult completo se pasa a
`reporting.aggregator` para el gate de liberacion (S11).
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from ..adapters.base import SutAdapter
from ..config import RobotQaConfig
from ..evaluators import REGISTRY, EvaluatorContext
from ..evidence import save_case, save_manifest, save_observation
from ..models import CampaignResult, CaseResult, Observation, Score, TestCase, Verdict
from ..judge import JudgeFn
from .registry import load_cases


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_rev(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_root,
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "desconocido"
    except Exception:
        return "desconocido"


def _load_ground_truth(datasets_dir: Path) -> dict:
    path = datasets_dir / "references" / "ground_truth.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _case_verdict(scores: list[Score]) -> Verdict:
    if not scores:
        return Verdict.ERROR
    relevantes = [s for s in scores if s.evaluator_id != "human_review"]
    critical_fail = any((not s.passed) and s.critical for s in relevantes)
    if critical_fail:
        return Verdict.FAIL
    if relevantes and not all(s.passed for s in relevantes):
        return Verdict.FAIL
    encolado = any(s.evaluator_id == "human_review" and s.detail.startswith("encolado") for s in scores)
    return Verdict.HUMAN_REVIEW if encolado else Verdict.PASS


def _consistency(observations: list[Observation], scores: list[Score]) -> float | None:
    """Acuerdo entre repeticiones (Guia S7 'Consistency'): fraccion de repeticiones
    cuyo resultado (todos los evaluadores no-criticos pasaron) coincide con la mayoria."""
    reps = sorted({o.repetition for o in observations})
    if len(reps) < 2:
        return None
    outcomes = []
    for r in reps:
        rep_scores = [s for s in scores if s.repetition == r and s.evaluator_id != "human_review"]
        outcomes.append(all(s.passed for s in rep_scores) if rep_scores else False)
    mayoria = outcomes.count(True) >= len(outcomes) / 2
    acuerdo = sum(1 for o in outcomes if o == mayoria) / len(outcomes)
    return acuerdo


def save_observation(evidence_dir: Path, observation: Observation) -> None:
    """Persiste CUALQUIER Observation (de un caso de la campana o de una variante
    metamorfica generada al vuelo) para que `--replay` pueda reconstruirla sin
    volver a llamar al SUT ni al LLM (Guia S10: reproducibilidad)."""
    obs_dir = evidence_dir / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    path = obs_dir / f"{observation.case_id}__rep{observation.repetition}.json"
    path.write_text(
        json.dumps(observation.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )




def run_campaign(
    campaign_name: str,
    campaign_cfg: dict,
    config: RobotQaConfig,
    adapter: SutAdapter,
    judge: JudgeFn | None,
    *,
    run_id: str | None = None,
    only_case_ids: list[str] | None = None,
) -> CampaignResult:
    started_at = _now_iso()
    run_id = run_id or f"{campaign_name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    evidence_dir = config.evidence_dir / run_id

    cases = load_cases(config.testcases_dir, campaign_cfg["suites"])
    if only_case_ids:
        wanted = set(only_case_ids)
        cases = [c for c in cases if c.case_id in wanted]

    ground_truth = _load_ground_truth(config.datasets_dir)
    default_repetitions = campaign_cfg.get("default_repetitions", 1)
    thresholds = {**config.default_thresholds, **campaign_cfg.get("thresholds", {})}

    manifest = {
        "run_id": run_id, "campaign": campaign_name,
        "sut_commit": _git_rev(config.sut_root),
        "robot_commit": _git_rev(config.sut_root / "robot-qa"),
        "sut_base_url": config.base_url,
        "llm_provider": "gemini", "llm_model": config.gemini.model,
        "n_cases": len(cases), "default_repetitions": default_repetitions,
        "thresholds": thresholds, "started_at": started_at,
    }

    case_results: list[CaseResult] = []
    for i, case in enumerate(cases, start=1):
        reps = max(1, case.repetitions or default_repetitions)
        action = case.input.get("action", "?")
        print(f"[{i}/{len(cases)}] {case.case_id} ({case.category}, accion={action}, "
              f"{reps} rep.) ejecutando...", end="", flush=True)
        t_case = time.perf_counter()
        observations: list[Observation] = []
        for r in range(reps):
            obs = adapter.invoke(case, repetition=r, run_id=run_id)
            observations.append(obs)
            save_observation(evidence_dir, obs)
            print(".", end="", flush=True)

        scores: list[Score] = []
        for obs in observations:
            sibling: list[Score] = []
            for ev_id in case.evaluators:
                evaluator = REGISTRY.get(ev_id)
                if evaluator is None:
                    sibling_score = Score(
                        evaluator_id=ev_id, case_id=case.case_id, repetition=obs.repetition,
                        value=0.0, passed=False, critical=True, detail=f"evaluador desconocido: {ev_id}",
                    )
                else:
                    ctx = EvaluatorContext(
                        run_id=run_id, adapter=adapter, ground_truth=ground_truth,
                        thresholds=thresholds, judge=judge, evidence_dir=evidence_dir,
                        sibling_scores=sibling,
                    )
                    sibling_score = evaluator.evaluate(case, obs, ctx)
                scores.append(sibling_score)
                sibling.append(sibling_score)

        verdict = _case_verdict(scores)
        consistency = _consistency(observations, scores)
        case_results.append(CaseResult(
            case=case, observations=observations, scores=scores,
            verdict=verdict, consistency=consistency,
        ))
        save_case(evidence_dir, case, observations, scores)
        print(f" {verdict.value} ({time.perf_counter() - t_case:.1f}s)", flush=True)

    manifest["finished_at"] = _now_iso()
    save_manifest(evidence_dir, manifest)

    result = CampaignResult(
        run_id=run_id, campaign=campaign_name, started_at=started_at,
        finished_at=manifest["finished_at"], cases=case_results, manifest=manifest,
    )
    return result
