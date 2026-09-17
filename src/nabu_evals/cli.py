from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from nabu_evals.annomi import generate_annomi
from nabu_evals.audit import audit_directory, render_audit
from nabu_evals.campaign import guidance_for_hash, run_campaign
from nabu_evals.evaluation import run_evaluation
from nabu_evals.generate import generate_semeval_propaganda, split_legacy_codebook
from nabu_evals.generators.epitome import generate_epitome
from nabu_evals.gold import GoldValidationError, coverage_probe, load_gold_root
from nabu_evals.optimizer import (
    DEFAULT_BRIDGE_URL,
    DEFAULT_MODEL_TABLE,
    DEFAULT_REFLECTION_MODEL,
    EVALUATION_MODEL_TABLES,
    OptimizerSettings,
    run_optimizer,
)
from nabu_evals.report import render_campaign_report
from nabu_evals.runtime import RuntimeFailure
from nabu_evals.stability import render_stability, stability_of


def _add_runtime_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--frontend", type=Path, required=True)
    command.add_argument("--prompts", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--max-candidate-proposals", type=int, default=1)
    command.add_argument("--chancery-bin", default="chancery")
    command.add_argument("--dragoman-bin", default="dragoman")
    command.add_argument("--reflection-model", default=DEFAULT_REFLECTION_MODEL)
    command.add_argument("--npm-bin", default="npm")
    command.add_argument(
        "--model-table",
        choices=EVALUATION_MODEL_TABLES,
        default=DEFAULT_MODEL_TABLE,
    )
    command.add_argument("--bridge-url", default=DEFAULT_BRIDGE_URL)
    command.add_argument("--per-root-timeout", type=int, default=1_800)
    command.add_argument("--total-timeout", type=int, default=7_200)
    command.add_argument("--max-frontend-invocations", type=int, default=100)
    command.add_argument("--max-coding-requests", type=int, default=200)
    command.add_argument(
        "--coding-profile",
        choices=("single-coder-direct", "two-voter-adjudicated"),
        default="single-coder-direct",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nabu-evals")
    commands = parser.add_subparsers(dest="command", required=True)
    optimize = commands.add_parser(
        "optimize", help="optimize qualitative-coding guidance"
    )
    optimize.add_argument("gold_roots", metavar="GOLD_ROOT", nargs="+")
    _add_runtime_options(optimize)
    evaluate = commands.add_parser(
        "evaluate", help="score one unchanged coding configuration without proposals"
    )
    evaluate.add_argument("gold_roots", metavar="GOLD_ROOT", nargs="+")
    evaluate.add_argument(
        "--coverage-probe-documents",
        type=int,
        metavar="COUNT",
        help="evaluate at most COUNT deterministic label-coverage documents per root",
    )
    evaluate.add_argument(
        "--guidance-file",
        type=Path,
        help="evaluate this complete general coding-guidance Markdown file without editing the source prompt",
    )
    _add_runtime_options(evaluate)
    campaign = commands.add_parser(
        "campaign",
        help="optimize development roots, then score the winner on comparison roots",
    )
    campaign.add_argument(
        "--development-root", type=Path, action="append", required=True
    )
    campaign.add_argument(
        "--comparison-root", type=Path, action="append", required=True
    )
    campaign.add_argument(
        "--coverage-probe-documents",
        type=int,
        metavar="COUNT",
        help="evaluate at most COUNT deterministic label-coverage documents per development and comparison root",
    )
    _add_runtime_options(campaign)
    report = commands.add_parser(
        "report", help="render a completed campaign's scores and decision as a PNG"
    )
    report.add_argument("run_directory", metavar="RUN_DIRECTORY", type=Path)
    report.add_argument("--output", type=Path)
    audit = commands.add_parser(
        "audit", help="explain score mechanics in stored results without rerunning"
    )
    audit.add_argument("run_directory", metavar="RUN_DIRECTORY", type=Path)
    audit.add_argument("--output", type=Path)
    audit.add_argument("--format", choices=("text", "json"), default="text")
    stability = commands.add_parser(
        "stability",
        help="summarize variation across repeated compatible coding evaluations",
    )
    stability.add_argument(
        "run_directories", metavar="RUN_DIRECTORY", nargs="+", type=Path
    )
    stability.add_argument("--output", type=Path)
    stability.add_argument("--format", choices=("text", "json"), default="text")
    generate = commands.add_parser(
        "generate",
        help="generate normal gold roots from raw datasets or legacy codebooks",
    )
    generators = generate.add_subparsers(dest="generator", required=True)
    migrate = generators.add_parser(
        "migrate-codebook",
        help="split legacy codebook.md files into normal coding sources",
    )
    migrate.add_argument("gold_roots", metavar="GOLD_ROOT", nargs="+")
    semeval = generators.add_parser(
        "semeval-propaganda", help="generate a gold root from SemEval-2020 Task 11 PTC"
    )
    semeval.add_argument("data_dir", metavar="DATA_DIR", type=Path)
    semeval.add_argument("output", metavar="OUTPUT", type=Path)
    annomi = generators.add_parser(
        "annomi", help="generate a gold root from AnnoMI-full.csv"
    )
    annomi.add_argument("data_dir", metavar="DATA_DIR", type=Path)
    annomi.add_argument("output", metavar="OUTPUT", type=Path)
    epitome = generators.add_parser(
        "epitome", help="generate a gold root from EPITOME CSVs"
    )
    epitome.add_argument("data_dir", metavar="DATA_DIR", type=Path)
    epitome.add_argument("output", metavar="OUTPUT", type=Path)
    return parser


def _runtime_executable(command: str) -> str:
    """Keep a bare PATH command bare; anchor a supplied path at the CLI cwd."""
    if "/" not in command and not command.startswith("~"):
        return command
    return str(Path(command).expanduser().resolve())


def _settings(args: argparse.Namespace, output: Path) -> OptimizerSettings:
    return OptimizerSettings(
        frontend=args.frontend.expanduser().resolve(),
        prompts=args.prompts.expanduser().resolve(),
        output=output,
        chancery_bin=_runtime_executable(args.chancery_bin),
        dragoman_bin=_runtime_executable(args.dragoman_bin),
        reflection_model=args.reflection_model,
        npm_bin=args.npm_bin,
        model_table=args.model_table,
        bridge_url=args.bridge_url,
        max_candidate_proposals=args.max_candidate_proposals,
        per_root_timeout=args.per_root_timeout,
        total_timeout=args.total_timeout,
        max_frontend_invocations=args.max_frontend_invocations,
        max_coding_requests=args.max_coding_requests,
        coding_profile=args.coding_profile,
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _optimize(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError(f"Output path already exists: {args.output}")
    roots = [load_gold_root(Path(path)) for path in args.gold_roots]
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True)
    manifest: dict[str, object] = {
        "kind": "optimization-set-proposal",
        "created_at": datetime.now(UTC).isoformat(),
        "target": "qual-coding",
        "frontend": str(args.frontend.expanduser().resolve()),
        "prompts": str(args.prompts.expanduser().resolve()),
        "max_candidate_proposals": args.max_candidate_proposals,
        "coding_profile": args.coding_profile,
        "roots": [root.manifest() for root in roots],
        "limits": {
            "per_root_seconds": args.per_root_timeout,
            "total_seconds": args.total_timeout,
            "frontend_invocations": args.max_frontend_invocations,
            "coding_requests_per_root": args.max_coding_requests,
        },
        "status": "running",
    }
    _write_json(output / "run.json", manifest)
    try:
        manifest["result"] = run_optimizer(_settings(args, output), roots)
        manifest["status"] = "complete"
    except Exception as error:
        manifest["status"] = "invalid"
        manifest["error"] = str(error)
        raise
    finally:
        _write_json(output / "run.json", manifest)


def _evaluate(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError(f"Output path already exists: {args.output}")
    roots = [load_gold_root(Path(path)) for path in args.gold_roots]
    if args.coverage_probe_documents is not None:
        roots = [coverage_probe(root, args.coverage_probe_documents) for root in roots]
    guidance = (
        args.guidance_file.expanduser().resolve().read_text(encoding="utf-8")
        if args.guidance_file is not None
        else None
    )
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True)
    manifest: dict[str, object] = {
        "kind": "fixed-coding-evaluation",
        "created_at": datetime.now(UTC).isoformat(),
        "target": "qual-coding",
        "frontend": str(args.frontend.expanduser().resolve()),
        "prompts": str(args.prompts.expanduser().resolve()),
        "model_table": args.model_table,
        "coding_profile": args.coding_profile,
        "guidance_file": (
            str(args.guidance_file.expanduser().resolve())
            if args.guidance_file is not None
            else None
        ),
        "roots": [root.manifest() for root in roots],
        "limits": {
            "per_root_seconds": args.per_root_timeout,
            "total_seconds": args.total_timeout,
            "frontend_invocations": args.max_frontend_invocations,
            "coding_requests_per_root": args.max_coding_requests,
        },
        "status": "running",
    }
    _write_json(output / "run.json", manifest)
    try:
        result = run_evaluation(_settings(args, output), roots, guidance)
        manifest["result"] = result
        manifest["status"] = "complete"
        _write_json(output / "evaluation.json", result)
    except Exception as error:
        manifest["status"] = "invalid"
        manifest["error"] = str(error)
        raise
    finally:
        _write_json(output / "run.json", manifest)


def _campaign(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError(f"Output path already exists: {args.output}")
    development_roots = [load_gold_root(root) for root in args.development_root]
    comparison_roots = [load_gold_root(root) for root in args.comparison_root]
    if args.coverage_probe_documents is not None:
        development_roots = [
            coverage_probe(root, args.coverage_probe_documents)
            for root in development_roots
        ]
        comparison_roots = [
            coverage_probe(root, args.coverage_probe_documents)
            for root in comparison_roots
        ]
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True)
    manifest: dict[str, object] = {
        "kind": "evaluation-campaign",
        "created_at": datetime.now(UTC).isoformat(),
        "target": "qual-coding",
        "development_roots": [root.manifest() for root in development_roots],
        "comparison_roots": [root.manifest() for root in comparison_roots],
        "coding_profile": args.coding_profile,
        "status": "running",
    }
    _write_json(output / "run.json", manifest)
    try:
        result = run_campaign(
            _settings(args, output), development_roots, comparison_roots
        )
        manifest["result"] = result
        manifest["status"] = "complete"
        _write_json(output / "comparison.json", result["comparison"])
        selected_hash = (
            result["comparison"]["winner_hash"]
            if result["comparison"]["accepted"]
            else result["development"]["candidates"][0]["hash"]
        )
        (output / "selected-coding-guidance.md").write_text(
            guidance_for_hash(output / "development", selected_hash) + "\n",
            encoding="utf-8",
        )
    except Exception as error:
        manifest["status"] = "invalid"
        manifest["error"] = str(error)
        raise
    finally:
        _write_json(output / "run.json", manifest)


def _audit(args: argparse.Namespace) -> None:
    audit = audit_directory(args.run_directory)
    rendered = (
        json.dumps(audit, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else render_audit(audit)
    )
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.expanduser().resolve().write_text(rendered, encoding="utf-8")


def _stability(args: argparse.Namespace) -> None:
    summary = stability_of(args.run_directories)
    rendered = (
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else render_stability(summary)
    )
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.expanduser().resolve().write_text(rendered, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    try:
        args = _parser().parse_args(argv)
        if args.command == "optimize":
            _optimize(args)
        if args.command == "evaluate":
            _evaluate(args)
        if args.command == "campaign":
            _campaign(args)
        if args.command == "report":
            render_campaign_report(args.run_directory, args.output)
        if args.command == "audit":
            _audit(args)
        if args.command == "stability":
            _stability(args)
        if args.command == "generate":
            if args.generator == "migrate-codebook":
                for root in args.gold_roots:
                    split_legacy_codebook(Path(root))
            if args.generator == "semeval-propaganda":
                generate_semeval_propaganda(args.data_dir, args.output)
            if args.generator == "annomi":
                generate_annomi(args.data_dir, args.output)
            if args.generator == "epitome":
                generate_epitome(args.data_dir, args.output)
    except (
        GoldValidationError,
        OSError,
        RuntimeFailure,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
