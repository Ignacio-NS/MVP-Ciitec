"""CLI del robot (Guia S5, "Runner": CLI y API).

    python -m robot_qa run --campaign smoke
    python -m robot_qa run --campaign full --repetitions 3 --save-baseline
    python -m robot_qa run --campaign full --replay <run_id>
    python -m robot_qa list-cases --campaign full
    python -m robot_qa calibrate <run_id>

Codigo de salida (Guia S5, "CI Connector"): 0 = PASS, 1 = HUMAN_REVIEW, 2 = REJECT.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import ApiAdapter, ReplayAdapter
from .config import load_config
from .judge import make_judge
from .models import Gate
from .reporting import (
    compare_to_baseline, compute_metrics, decide_gate,
    write_html_report, write_junit_report,
)
from .reporting.baseline_diff import load_baseline, save_baseline
from .runner import load_campaign_config, run_campaign


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config()
    campaign_cfg = load_campaign_config(config.campaigns_dir, args.campaign)

    only_ids = args.cases.split(",") if args.cases else None

    if args.replay:
        source_dir = config.evidence_dir / args.replay
        adapter = ReplayAdapter(source_dir)
        print(f"[replay] sirviendo evidencia de {source_dir} (sin llamar al SUT ni al LLM)")
    else:
        adapter = ApiAdapter(config.base_url, config.users, verify=config.verify_tls, sut_root=config.sut_root)

    judge = None if args.no_judge else make_judge(config.gemini, config.rubrics_dir)
    if judge is None and not args.no_judge:
        print("[aviso] GEMINI_API_KEY no configurada: 'rubric_llm' marcara sus casos como no evaluados")

    try:
        result = run_campaign(
            args.campaign, campaign_cfg, config, adapter, judge,
            run_id=args.run_id, only_case_ids=only_ids,
        )
    finally:
        adapter.close()

    result.metrics = compute_metrics(result)
    gate, reason = decide_gate(result, result.metrics, campaign_cfg.get("thresholds", {}))
    result.gate, result.gate_reason = gate, reason

    reports_dir = config.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{result.run_id}.json").write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str), encoding="utf-8",
    )
    html_path = write_html_report(result, reports_dir / f"{result.run_id}.html")
    write_html_report(result, reports_dir / "latest.html")
    write_junit_report(result, reports_dir / f"{result.run_id}.junit.xml")

    baseline_path = reports_dir / "baseline.json"
    baseline = load_baseline(baseline_path)
    if baseline is not None:
        diff = compare_to_baseline(result, baseline, campaign_cfg.get("baseline_tolerance", {}))
        (reports_dir / f"{result.run_id}.diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        if diff["regressions_detected"]:
            print(f"[baseline] REGRESION detectada vs {baseline.run_id}: "
                  f"nuevas fallas={diff['new_failures']}, metricas peores="
                  f"{[k for k, v in diff['metric_diffs'].items() if v['regressed']]}")
        else:
            print(f"[baseline] sin regresiones vs {baseline.run_id}")

    if args.save_baseline:
        save_baseline(result, baseline_path)
        print(f"[baseline] guardada como nueva linea base: {baseline_path}")

    _print_summary(result)
    print(f"reporte: {html_path}")

    return {Gate.PASS: 0, Gate.HUMAN_REVIEW: 1, Gate.REJECT: 2}[result.gate]


def _print_summary(result) -> None:
    m = result.metrics
    print(f"\n=== {result.campaign} ({result.run_id}) ===")
    print(f"GATE: {result.gate.value} — {result.gate_reason}")
    print(f"casos: {m.get('n_cases')}  success_rate={m.get('task_success_rate', 0):.1%}  "
          f"fail_rate={m.get('fail_rate', 0):.1%}  human_review={m.get('human_review_rate', 0):.1%}")
    if "groundedness" in m:
        print(f"groundedness={m['groundedness']:.2f}  hallucination_rate_proxy={m['hallucination_rate_proxy']:.2f}")
    if "attack_success_rate" in m:
        print(f"attack_success_rate={m['attack_success_rate']:.1%}")
    if "latency_p95_s" in m:
        print(f"latency p50={m.get('latency_p50_s', 0):.1f}s p95={m['latency_p95_s']:.1f}s")


def _cmd_list_cases(args: argparse.Namespace) -> int:
    config = load_config()
    campaign_cfg = load_campaign_config(config.campaigns_dir, args.campaign)
    from .runner.registry import load_cases
    cases = load_cases(config.testcases_dir, campaign_cfg["suites"])
    for c in cases:
        print(f"{c.case_id:<22} {c.category:<14} {c.requirement_id:<10} sev={c.severity:<8} "
              f"reps={c.repetitions}  evaluators={','.join(c.evaluators)}")
    print(f"\ntotal: {len(cases)} casos en {len(campaign_cfg['suites'])} suite(s)")
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    config = load_config()
    evidence_dir = config.evidence_dir / args.run_id
    queue_path = evidence_dir / "human_review_queue.jsonl"
    verdicts_path = evidence_dir / "human_verdicts.json"

    if not queue_path.is_file():
        print(f"no hay cola de revision humana en {queue_path} (¿corriste la campana con el evaluador 'human_review'?)")
        return 1

    queued = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    case_ids = sorted({q["case_id"] for q in queued})

    if not verdicts_path.is_file():
        template = {cid: {"passed": None, "reviewer": "", "notes": ""} for cid in case_ids}
        verdicts_path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"plantilla creada en {verdicts_path} — completa 'passed' (true/false) y 'reviewer' para cada "
              f"caso y vuelve a correr 'calibrate' para calcular el acuerdo.")
        return 1

    verdicts = json.loads(verdicts_path.read_text(encoding="utf-8"))
    pendientes = [cid for cid in case_ids if verdicts.get(cid, {}).get("passed") is None]
    if pendientes:
        print(f"faltan veredictos humanos para: {pendientes}")
        return 1

    coincide = 0
    total = 0
    detalle = []
    for cid in case_ids:
        case_path = evidence_dir / "cases" / f"{cid}.json"
        if not case_path.is_file():
            continue
        data = json.loads(case_path.read_text(encoding="utf-8"))
        judge_scores = [s for s in data["scores"] if s["evaluator_id"] == "rubric_llm"]
        if not judge_scores:
            continue
        juez_passed = judge_scores[0]["passed"]
        humano_passed = bool(verdicts[cid]["passed"])
        acuerdo = juez_passed == humano_passed
        coincide += int(acuerdo)
        total += 1
        detalle.append({"case_id": cid, "juez": juez_passed, "humano": humano_passed, "acuerdo": acuerdo})

    agreement = coincide / total if total else None
    out = {"run_id": args.run_id, "human_agreement": agreement, "n_comparados": total, "detalle": detalle}
    (evidence_dir / "human_agreement.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"human_agreement = {agreement:.1%} ({coincide}/{total})" if total else "sin casos comparables")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="robot_qa")
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="ejecuta una campana")
    run_p.add_argument("--campaign", required=True)
    run_p.add_argument("--run-id", default=None)
    run_p.add_argument("--cases", default=None, help="lista de case_id separados por coma (subconjunto)")
    run_p.add_argument("--replay", default=None, metavar="RUN_ID", help="reusa evidencia de una corrida previa")
    run_p.add_argument("--save-baseline", action="store_true")
    run_p.add_argument("--no-judge", action="store_true", help="desactiva el juez LLM (rubric_llm)")
    run_p.set_defaults(func=_cmd_run)

    list_p = sub.add_parser("list-cases", help="lista los casos de una campana")
    list_p.add_argument("--campaign", required=True)
    list_p.set_defaults(func=_cmd_list_cases)

    cal_p = sub.add_parser("calibrate", help="calcula el acuerdo juez-LLM vs revision humana")
    cal_p.add_argument("run_id")
    cal_p.set_defaults(func=_cmd_calibrate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
