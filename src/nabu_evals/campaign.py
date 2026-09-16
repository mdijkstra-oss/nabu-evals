from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from nabu_evals.gold import GoldRoot
from nabu_evals.optimizer import OptimizerSettings, run_optimizer
from nabu_evals.runtime import DragomanRuntime, RuntimeSettings
from nabu_evals.target import QualCodingTarget, candidate_hash


def guidance_for_hash(output: Path, digest: str) -> str:
    for path in (output / "candidates").glob("*/coding-guidance.md"):
        guidance = path.read_text(encoding="utf-8").rstrip()
        if candidate_hash(guidance) == digest:
            return guidance
    raise RuntimeError(f"missing development candidate {digest}")


def _comparison_summary(
    settings: OptimizerSettings,
    roots: list[GoldRoot],
    development: dict[str, Any],
) -> dict[str, Any]:
    baseline = (
        (settings.prompts / "config/deep-analysis-filter/coding-guidance.md")
        .read_text(encoding="utf-8")
        .rstrip()
    )
    winner_index = int(development["best_index"])
    winner_hash = str(development["candidates"][winner_index]["hash"])
    winner = guidance_for_hash(settings.output / "development", winner_hash)
    runtime = RuntimeSettings(
        prompts=settings.prompts,
        output=settings.output / "comparison",
        chancery_bin=settings.chancery_bin,
        dragoman_bin=settings.dragoman_bin,
        model_table=settings.model_table,
        bridge_url=settings.bridge_url,
    )
    with DragomanRuntime(runtime) as dragoman:
        target = QualCodingTarget(
            roots=roots,
            runtime=runtime,
            frontend=settings.frontend,
            npm_bin=settings.npm_bin,
            dragoman_port=dragoman.port,
            per_root_timeout=settings.per_root_timeout,
            max_frontend_invocations=settings.max_frontend_invocations,
            max_coding_requests=settings.max_coding_requests,
            total_deadline=time.monotonic() + settings.total_timeout,
            baseline=baseline,
        )
        baseline_scored = target.evaluate_batch([(baseline, root) for root in roots])
        winner_scored = (
            baseline_scored
            if candidate_hash(winner) == candidate_hash(baseline)
            else target.evaluate_batch([(winner, root) for root in roots])
        )
    baseline_scores = [score for score, _ in baseline_scored]
    winner_scores = [score for score, _ in winner_scored]
    deltas = [
        winner_score - baseline_score
        for baseline_score, winner_score in zip(
            baseline_scores, winner_scores, strict=True
        )
    ]
    mean_delta = sum(deltas) / len(deltas)
    return {
        "kind": "protected-comparison",
        "winner_index": winner_index,
        "winner_hash": winner_hash,
        "baseline_mean_f1": sum(baseline_scores) / len(baseline_scores),
        "winner_mean_f1": sum(winner_scores) / len(winner_scores),
        "mean_delta": mean_delta,
        "minimum_root_delta": min(deltas),
        "accepted": mean_delta > 0 and min(deltas) >= 0,
        "roots": [
            {
                "root": root.name,
                "baseline_f1": baseline_score,
                "winner_f1": winner_score,
                "delta": delta,
            }
            for root, baseline_score, winner_score, delta in zip(
                roots, baseline_scores, winner_scores, deltas, strict=True
            )
        ],
    }


def run_campaign(
    settings: OptimizerSettings,
    development_roots: list[GoldRoot],
    comparison_roots: list[GoldRoot],
) -> dict[str, Any]:
    development = run_optimizer(
        replace(settings, output=settings.output / "development"), development_roots
    )
    comparison = _comparison_summary(settings, comparison_roots, development)
    return {"development": development, "comparison": comparison}
