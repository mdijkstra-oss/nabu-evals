from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, stdev
from typing import Any


class StabilityError(ValueError):
    """Completed evaluations cannot be treated as repeated measurements."""


@dataclass(frozen=True)
class _Root:
    name: str
    hash: str
    documents: tuple[str, ...]


@dataclass(frozen=True)
class _Evaluation:
    model_table: str
    coding_profile: dict[str, Any]
    evaluated_guidance: dict[str, Any]
    roots: tuple[_Root, ...]
    scores: dict[str, float]


def _object(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StabilityError(f"{context} must be a JSON object")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise StabilityError(f"{context} must be a non-empty string")
    return value


def _read_object(path: Path) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except OSError as error:
        raise StabilityError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise StabilityError(f"cannot parse {path}: {error}") from error


def _evaluation_of(directory: Path) -> _Evaluation:
    run = _read_object(directory / "run.json")
    if run.get("kind") != "fixed-coding-evaluation" or run.get("status") != "complete":
        raise StabilityError(f"{directory} is not a completed fixed coding evaluation")
    result = _read_object(directory / "evaluation.json")
    manifest = run.get("roots")
    results = result.get("roots")
    if not isinstance(manifest, list) or not manifest:
        raise StabilityError(f"{directory} has no evaluated roots")
    if not isinstance(results, list) or not results:
        raise StabilityError(f"{directory} has no root scores")

    scores: dict[str, float] = {}
    for entry in results:
        value = _object(entry, f"{directory} evaluation root")
        name = _string(value.get("root"), f"{directory} evaluation root name")
        if name in scores:
            raise StabilityError(f"{directory} repeats root score {name!r}")
        try:
            scores[name] = float(value["score"])
        except (KeyError, TypeError, ValueError) as error:
            raise StabilityError(
                f"{directory} has invalid score for {name!r}"
            ) from error

    roots: list[_Root] = []
    for entry in manifest:
        value = _object(entry, f"{directory} root manifest")
        name = _string(value.get("name"), f"{directory} root name")
        digest = _string(value.get("hash"), f"{directory} root hash")
        documents = value.get("documents")
        if not isinstance(documents, list) or not all(
            isinstance(document, str) for document in documents
        ):
            raise StabilityError(f"{directory} has invalid documents for {name!r}")
        if name not in scores:
            raise StabilityError(f"{directory} is missing score for {name!r}")
        roots.append(_Root(name, digest, tuple(documents)))
    if len({root.name for root in roots}) != len(roots):
        raise StabilityError(f"{directory} repeats a root name")
    if set(scores) != {root.name for root in roots}:
        raise StabilityError(f"{directory} root score and manifest sets differ")

    guidance = result.get("evaluated_guidance")
    if guidance is None:
        evaluated_guidance = {
            "kind": "legacy-source-tree",
            "hash": _string(
                result.get("source_prompt_hash"), f"{directory} source prompt hash"
            ),
        }
    else:
        evaluated_guidance = _object(guidance, f"{directory} evaluated guidance")

    return _Evaluation(
        model_table=_string(result.get("model_table"), f"{directory} model table"),
        coding_profile=_object(
            result.get("coding_profile"), f"{directory} coding profile"
        ),
        evaluated_guidance=evaluated_guidance,
        roots=tuple(roots),
        scores=scores,
    )


def _ensure_compatible(reference: _Evaluation, other: _Evaluation) -> None:
    if other.model_table != reference.model_table:
        raise StabilityError("cannot combine evaluations with different model tables")
    if other.coding_profile != reference.coding_profile:
        raise StabilityError(
            "cannot combine evaluations with different coding profiles"
        )
    if other.evaluated_guidance != reference.evaluated_guidance:
        raise StabilityError(
            "cannot combine evaluations with different evaluated guidance"
        )
    if other.roots != reference.roots:
        raise StabilityError("cannot combine evaluations with different selected roots")


def stability_of(directories: list[Path]) -> dict[str, Any]:
    """Describe repeat-run variation for an identical fixed evaluation setup."""
    if len(directories) < 2:
        raise StabilityError("stability requires at least two completed evaluations")
    evaluations = [
        _evaluation_of(directory.expanduser().resolve()) for directory in directories
    ]
    reference = evaluations[0]
    for evaluation in evaluations[1:]:
        _ensure_compatible(reference, evaluation)

    roots = []
    for root in reference.roots:
        scores = [evaluation.scores[root.name] for evaluation in evaluations]
        roots.append(
            {
                "name": root.name,
                "hash": root.hash,
                "documents": list(root.documents),
                "replicates": len(scores),
                "scores": scores,
                "mean_f1": fmean(scores),
                "minimum_f1": min(scores),
                "maximum_f1": max(scores),
                "sample_stddev": stdev(scores),
            }
        )
    return {
        "kind": "coding-evaluation-stability",
        "scope": "Repeated model executions only; this is not human inter-rater agreement.",
        "run_count": len(evaluations),
        "model_table": reference.model_table,
        "coding_profile": reference.coding_profile,
        "evaluated_guidance": reference.evaluated_guidance,
        "roots": roots,
    }


def render_stability(summary: dict[str, Any]) -> str:
    """Render a compact, non-inferential repeat-run stability report."""
    lines = [
        "Model-run stability",
        str(summary["scope"]),
        f"Runs: {summary['run_count']}; model table: {summary['model_table']}",
        "",
    ]
    for root in summary["roots"]:
        lines.append(
            f"{root['name']}: mean F1 {root['mean_f1']:.3f}; "
            f"range {root['minimum_f1']:.3f}–{root['maximum_f1']:.3f}; "
            f"sample SD {root['sample_stddev']:.3f} across {root['replicates']} runs"
        )
    return "\n".join(lines) + "\n"
