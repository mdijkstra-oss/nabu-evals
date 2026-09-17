from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nabu_evals.gold import GoldRoot
from nabu_evals.optimizer import OptimizerSettings
from nabu_evals.runtime import DragomanRuntime, RuntimeSettings
from nabu_evals.target import QualCodingTarget, candidate_hash, coding_profile


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_evaluation(
    settings: OptimizerSettings,
    roots: Sequence[GoldRoot],
    guidance: str | None = None,
) -> dict[str, Any]:
    """Run one fixed guidance component, with no reflection or proposal step."""
    guidance_path = settings.prompts / "config/deep-analysis-filter/coding-guidance.md"
    baseline = guidance_path.read_text(encoding="utf-8").rstrip()
    evaluated_guidance = baseline if guidance is None else guidance.rstrip()
    prompt_root = settings.prompts / "config/deep-analysis-filter"
    source_prompt_hash = _tree_hash(prompt_root)
    runtime = RuntimeSettings(
        prompts=settings.prompts,
        output=settings.output,
        chancery_bin=settings.chancery_bin,
        dragoman_bin=settings.dragoman_bin,
        model_table=settings.model_table,
        bridge_url=settings.bridge_url,
    )
    profile = coding_profile(settings.coding_profile)
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
            total_evaluations=len(roots),
            profile=profile,
        )
        scored = target.evaluate_batch([(evaluated_guidance, root) for root in roots])
    if _tree_hash(prompt_root) != source_prompt_hash:
        raise RuntimeError("source prompt checkout changed during evaluation")
    return {
        "kind": "fixed-coding-evaluation",
        "source_prompt_hash": source_prompt_hash,
        "evaluated_guidance": {
            "kind": "source" if guidance is None else "supplied-file",
            "hash": candidate_hash(evaluated_guidance),
        },
        "coding_profile": profile.manifest(),
        "model_table": settings.model_table,
        "reflection_calls": 0,
        "frontend_invocations": target.frontend_invocations,
        "coding_requests": target.coding_requests,
        "roots": [
            {
                "root": root.name,
                "score": score,
                "metrics": feedback.get("metrics", {}),
            }
            for root, (score, feedback) in zip(roots, scored, strict=True)
        ],
    }
