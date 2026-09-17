from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nabu_evals.scoring import diagnose_comparison

_ALIGNMENT_SUMMARIES = ("sameCode", "wrongCodeAtOverlappingSpan")
_ALIGNMENT_FIELDS = ("matches", "exact", "relaxed", "weak", "totalIou")


def _totals(tp: float, fp: float, fn: float) -> dict[str, float]:
    precision = (
        1.0 if tp + fp == 0 and fn == 0 else 0.0 if tp + fp == 0 else tp / (tp + fp)
    )
    recall = (
        1.0 if tp + fn == 0 and fp == 0 else 0.0 if tp + fn == 0 else tp / (tp + fn)
    )
    f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _path_part(path: Path, name: str) -> str | None:
    try:
        index = path.parts.index(name)
    except ValueError:
        return None
    return path.parts[index + 1] if index + 1 < len(path.parts) else None


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _alignment_summary(documents: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        key: {field: 0 for field in _ALIGNMENT_FIELDS} for key in _ALIGNMENT_SUMMARIES
    }
    residual: dict[str, float] = {
        "predictions": 0,
        "gold": 0,
        "predictionResolverErrors": 0,
        "goldResolverErrors": 0,
    }
    summary["residual"] = residual
    presence = {"tp": 0.0, "fp": 0.0, "fn": 0.0}
    for document in documents:
        alignment = document.get("alignment")
        if not isinstance(alignment, dict):
            continue
        for key in _ALIGNMENT_SUMMARIES:
            source = alignment[key]
            for field in _ALIGNMENT_FIELDS:
                summary[key][field] += _number(source.get(field))
        for field in residual:
            residual[field] += _number(alignment["residual"].get(field))
        for field in presence:
            presence[field] += _number(alignment["codePresence"].get(field))
    summary["codePresence"] = _totals(**presence)
    return summary


def _pipeline_stages(result_path: Path) -> list[dict[str, Any]]:
    """Read count-only frontend stage telemetry when a modern artifact has it."""
    raw_path = result_path.with_name("coding-result.json")
    if not raw_path.is_file():
        return []
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    stages = raw.get("stages") if isinstance(raw, dict) else None
    return (
        [stage for stage in stages if isinstance(stage, dict)]
        if isinstance(stages, list)
        else []
    )


def audit_results(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Render one scored root artifact into a score-mechanics record."""
    documents: list[dict[str, Any]] = []
    raw_documents = result.get("documents", [])
    if not isinstance(raw_documents, list):
        raise TypeError(f"{path}: results documents must be a list")
    for raw_document in raw_documents:
        if not isinstance(raw_document, dict):
            continue
        comparison = raw_document.get("comparison")
        documents.append(
            {
                "name": raw_document.get("name"),
                "status": raw_document.get("status"),
                "scores": {
                    key: (comparison or {}).get(key)
                    for key in ("soft", "relaxed", "exact")
                },
                "alignment": (
                    diagnose_comparison(comparison)
                    if isinstance(comparison, dict)
                    else None
                ),
            }
        )
    return {
        "artifact": str(path),
        "candidate": _path_part(path, "candidates"),
        "root": _path_part(path, "roots"),
        "complete": result.get("complete") is True,
        "outcomes": result.get("outcomes", {}),
        "scores": {key: result.get(key) for key in ("soft", "relaxed", "exact")},
        "alignment": _alignment_summary(documents),
        "pipeline": {"stages": _pipeline_stages(path)},
        "documents": documents,
    }


def audit_directory(path: Path) -> dict[str, Any]:
    """Inspect stored scoring artifacts without rerunning or changing coding."""
    source = path.expanduser().resolve()
    result_paths = (
        [source]
        if source.name == "results.json" and source.is_file()
        else sorted(source.rglob("results.json"))
    )
    if not result_paths:
        raise ValueError(f"{source}: no results.json artifacts found")
    artifacts = []
    for result_path in result_paths:
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{result_path}: malformed JSON: {error}") from error
        if not isinstance(result, dict):
            raise TypeError(f"{result_path}: result must be an object")
        artifacts.append(audit_results(result_path, result))
    return {
        "kind": "coding-score-mechanics-audit",
        "scope": (
            "This decomposes how the stored score was produced; it does not decide "
            "whether a golden label is semantically right."
        ),
        "input": str(source),
        "artifactCount": len(artifacts),
        "artifacts": artifacts,
    }


def _f1(scores: object) -> str:
    if not isinstance(scores, dict):
        return "n/a"
    value = scores.get("f1")
    return f"{_number(value):.3f}" if isinstance(value, int | float) else "n/a"


def _stage_summary(stage: dict[str, Any]) -> str | None:
    name = stage.get("stage")
    if name == "candidates":
        return (
            f"candidates {stage.get('candidates')} across {stage.get('chunks')} chunks"
        )
    if name == "voters":
        selections = stage.get("selections")
        if isinstance(selections, dict):
            rendered = ", ".join(
                f"{coder} {count}" for coder, count in sorted(selections.items())
            )
            return f"voters ({rendered})"
    if name == "consensus":
        return f"consensus {stage.get('accepted')} agreed, {stage.get('contested')} contested"
    if name == "adjudication":
        return f"adjudication kept {stage.get('accepted')} of {stage.get('contested')} contested"
    if name == "decisions":
        return f"final decisions {stage.get('decisions')}"
    return None


def render_audit(audit: dict[str, Any]) -> str:
    """Create a short human-readable view while retaining the JSON audit schema."""
    lines = ["Coding score-mechanics audit", str(audit["scope"]), ""]
    for artifact in audit["artifacts"]:
        label = " / ".join(
            part
            for part in (artifact.get("candidate"), artifact.get("root"))
            if isinstance(part, str)
        ) or str(artifact["artifact"])
        scores = artifact["scores"]
        alignment = artifact["alignment"]
        same_code = alignment["sameCode"]
        wrong_code = alignment["wrongCodeAtOverlappingSpan"]
        residual = alignment["residual"]
        presence = alignment["codePresence"]
        stages = artifact["pipeline"]["stages"]
        stage_summary = "; ".join(
            summary
            for stage in stages
            if (summary := _stage_summary(stage)) is not None
        )
        lines.extend(
            [
                f"{label}: {'complete' if artifact['complete'] else 'incomplete'}",
                (
                    "  F1: "
                    f"soft {_f1(scores.get('soft'))}; "
                    f"relaxed {_f1(scores.get('relaxed'))}; "
                    f"exact {_f1(scores.get('exact'))}"
                ),
                (
                    "  same-code spans: "
                    f"{same_code['matches']} ({same_code['exact']} exact, "
                    f"{same_code['relaxed'] - same_code['exact']} boundary-close, "
                    f"{same_code['weak']} weak-overlap)"
                ),
                (
                    "  wrong-code at overlapping span: "
                    f"{wrong_code['matches']} ({wrong_code['exact']} exact-location)"
                ),
                (
                    "  no overlapping counterpart: "
                    f"{residual['predictions']} predicted, {residual['gold']} gold; "
                    "resolver errors: "
                    f"{residual['predictionResolverErrors']} predicted, "
                    f"{residual['goldResolverErrors']} gold"
                ),
                f"  document-level code presence F1 (span-agnostic): {presence['f1']:.3f}",
                *([f"  pipeline: {stage_summary}"] if stage_summary else []),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
