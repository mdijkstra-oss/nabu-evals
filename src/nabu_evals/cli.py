from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from nabu_evals.gold import GoldValidationError, load_gold_root
from nabu_evals.optimizer import OptimizerSettings, run_optimizer
from nabu_evals.runtime import RuntimeFailure


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nabu-evals")
    commands = parser.add_subparsers(dest="command", required=True)
    optimize = commands.add_parser(
        "optimize", help="optimize qualitative-coding guidance"
    )
    optimize.add_argument("gold_roots", metavar="GOLD_ROOT", nargs="+")
    optimize.add_argument("--frontend", type=Path, required=True)
    optimize.add_argument("--prompts", type=Path, required=True)
    optimize.add_argument("--output", type=Path, required=True)
    optimize.add_argument("--max-candidate-proposals", type=int, default=1)
    optimize.add_argument("--chancery-bin", default="chancery")
    optimize.add_argument("--dragoman-bin", default="dragoman")
    optimize.add_argument("--claude-bin", default="claude")
    optimize.add_argument("--reflection-model", default="opus")
    optimize.add_argument("--npm-bin", default="npm")
    optimize.add_argument("--model-table", default="models.claude-cli.yaml")
    optimize.add_argument("--bridge-url", default="http://127.0.0.1:8082")
    optimize.add_argument("--per-root-timeout", type=int, default=1_800)
    optimize.add_argument("--total-timeout", type=int, default=7_200)
    optimize.add_argument("--max-frontend-invocations", type=int, default=100)
    optimize.add_argument("--max-coding-requests", type=int, default=200)
    return parser


def _optimize(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError(f"Output path already exists: {args.output}")
    roots = [load_gold_root(Path(path)) for path in args.gold_roots]
    args.output.mkdir(parents=True)
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
    (args.output / "run.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    try:
        summary = run_optimizer(
            OptimizerSettings(
                frontend=args.frontend.expanduser().resolve(),
                prompts=args.prompts.expanduser().resolve(),
                output=args.output.resolve(),
                chancery_bin=args.chancery_bin,
                dragoman_bin=args.dragoman_bin,
                claude_bin=args.claude_bin,
                reflection_model=args.reflection_model,
                npm_bin=args.npm_bin,
                model_table=args.model_table,
                bridge_url=args.bridge_url,
                max_candidate_proposals=args.max_candidate_proposals,
                per_root_timeout=args.per_root_timeout,
                total_timeout=args.total_timeout,
                max_frontend_invocations=args.max_frontend_invocations,
                max_coding_requests=args.max_coding_requests,
            ),
            roots,
        )
        manifest["status"] = "complete"
        manifest["result"] = summary
    except Exception as error:
        manifest["status"] = "invalid"
        manifest["error"] = str(error)
        (args.output / "run.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    (args.output / "run.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> None:
    try:
        args = _parser().parse_args(argv)
        if args.command == "optimize":
            _optimize(args)
    except (
        GoldValidationError,
        OSError,
        RuntimeFailure,
        RuntimeError,
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
