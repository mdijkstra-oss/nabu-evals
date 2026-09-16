from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from nabu_evals.annomi import generate_annomi
from nabu_evals.campaign import guidance_for_hash, run_campaign
from nabu_evals.generate import generate_semeval_propaganda, split_legacy_codebook
from nabu_evals.generators.epitome import generate_epitome
from nabu_evals.gold import GoldValidationError, load_gold_root
from nabu_evals.optimizer import OptimizerSettings, run_optimizer
from nabu_evals.runtime import RuntimeFailure


def _add_runtime_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--frontend", type=Path, required=True)
    command.add_argument("--prompts", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--max-candidate-proposals", type=int, default=1)
    command.add_argument("--chancery-bin", default="chancery")
    command.add_argument("--dragoman-bin", default="dragoman")
    command.add_argument("--reflection-model", default="claude-cli/claude-opus-5")
    command.add_argument("--npm-bin", default="npm")
    command.add_argument("--model-table", default="models.claude-cli.yaml")
    command.add_argument("--bridge-url", default="http://127.0.0.1:8082")
    command.add_argument("--per-root-timeout", type=int, default=1_800)
    command.add_argument("--total-timeout", type=int, default=7_200)
    command.add_argument("--max-frontend-invocations", type=int, default=100)
    command.add_argument("--max-coding-requests", type=int, default=200)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nabu-evals")
    commands = parser.add_subparsers(dest="command", required=True)
    optimize = commands.add_parser(
        "optimize", help="optimize qualitative-coding guidance"
    )
    optimize.add_argument("gold_roots", metavar="GOLD_ROOT", nargs="+")
    _add_runtime_options(optimize)
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
    _add_runtime_options(campaign)
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


def _settings(args: argparse.Namespace, output: Path) -> OptimizerSettings:
    return OptimizerSettings(
        frontend=args.frontend.expanduser().resolve(),
        prompts=args.prompts.expanduser().resolve(),
        output=output,
        chancery_bin=args.chancery_bin,
        dragoman_bin=args.dragoman_bin,
        reflection_model=args.reflection_model,
        npm_bin=args.npm_bin,
        model_table=args.model_table,
        bridge_url=args.bridge_url,
        max_candidate_proposals=args.max_candidate_proposals,
        per_root_timeout=args.per_root_timeout,
        total_timeout=args.total_timeout,
        max_frontend_invocations=args.max_frontend_invocations,
        max_coding_requests=args.max_coding_requests,
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


def _campaign(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError(f"Output path already exists: {args.output}")
    development_roots = [load_gold_root(root) for root in args.development_root]
    comparison_roots = [load_gold_root(root) for root in args.comparison_root]
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True)
    manifest: dict[str, object] = {
        "kind": "evaluation-campaign",
        "created_at": datetime.now(UTC).isoformat(),
        "target": "qual-coding",
        "development_roots": [root.manifest() for root in development_roots],
        "comparison_roots": [root.manifest() for root in comparison_roots],
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


def main(argv: Sequence[str] | None = None) -> None:
    try:
        args = _parser().parse_args(argv)
        if args.command == "optimize":
            _optimize(args)
        if args.command == "campaign":
            _campaign(args)
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
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
