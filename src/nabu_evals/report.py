from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read report input {path}: {error}") from error
    if not isinstance(value, dict):
        raise TypeError(f"report input must be a JSON object: {path}")
    return value


def render_campaign_report(run_directory: Path, output: Path | None = None) -> Path:
    """Render the decision-relevant results of a completed campaign as a PNG."""
    run_directory = run_directory.expanduser().resolve()
    run = _read_object(run_directory / "run.json")
    if run.get("kind") != "evaluation-campaign" or run.get("status") != "complete":
        raise ValueError("report requires a completed evaluation campaign directory")
    scores = _read_object(run_directory / "development" / "scores.json")
    comparison = _read_object(run_directory / "comparison.json")
    candidates = scores.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("development scores contain no candidates")

    try:
        indices = [int(candidate["index"]) for candidate in candidates]
        development_scores = [float(candidate["score"]) for candidate in candidates]
        best_index = int(scores["best_index"])
        baseline_f1 = float(comparison["baseline_mean_f1"])
        winner_f1 = float(comparison["winner_mean_f1"])
        accepted = bool(comparison["accepted"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"campaign report has malformed score data: {error}"
        ) from error

    output = (output or run_directory / "evaluation-report.png").expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure, (development, protected) = pyplot.subplots(1, 2, figsize=(12, 5))

    development.plot(indices, development_scores, marker="o", color="#2563eb")
    development.scatter(
        [best_index],
        [development_scores[indices.index(best_index)]],
        color="#16a34a",
        marker="*",
        s=180,
        zorder=3,
        label="Best development candidate",
    )
    development.set(
        title="Development progress",
        xlabel="Candidate iteration (0 = baseline)",
        ylabel="Mean F1",
        ylim=(0, 1),
    )
    development.set_xticks(indices)
    development.grid(axis="y", alpha=0.25)
    development.legend(loc="lower right")

    protected.bar(
        ["Baseline", f"Dev winner\n(proposal {best_index})"],
        [baseline_f1, winner_f1],
        color=["#64748b", "#16a34a" if accepted else "#dc2626"],
    )
    protected.set(
        title=f"Protected comparison: {'accepted' if accepted else 'baseline retained'}",
        ylabel="Mean F1",
        ylim=(0, 1),
    )
    protected.grid(axis="y", alpha=0.25)
    for position, value in enumerate([baseline_f1, winner_f1]):
        protected.text(position, value + 0.02, f"{value:.3f}", ha="center")

    selected = f"Proposal {best_index}" if accepted else "Baseline"
    figure.suptitle(
        f"Nabu evaluation campaign — selected: {selected}", fontweight="bold"
    )
    figure.tight_layout()
    figure.savefig(output, dpi=180, bbox_inches="tight")
    pyplot.close(figure)
    return output
