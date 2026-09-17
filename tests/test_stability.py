from __future__ import annotations

import json
from pathlib import Path

import pytest

from nabu_evals.cli import main
from nabu_evals.stability import StabilityError, stability_of


def _write_evaluation(
    directory: Path,
    *,
    score: float,
    guidance_hash: str = "guidance-a",
    legacy_source_tree: bool = False,
) -> None:
    directory.mkdir()
    (directory / "run.json").write_text(
        json.dumps(
            {
                "kind": "fixed-coding-evaluation",
                "status": "complete",
                "roots": [
                    {
                        "name": "gold-a",
                        "hash": "gold-hash-a",
                        "documents": ["document.md"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (directory / "evaluation.json").write_text(
        json.dumps(
            {
                "model_table": "models.evaluation-cli-gpt.yaml",
                "coding_profile": {"name": "single-coder-direct"},
                **(
                    {"source_prompt_hash": guidance_hash}
                    if legacy_source_tree
                    else {
                        "evaluated_guidance": {
                            "kind": "source",
                            "hash": guidance_hash,
                        }
                    }
                ),
                "roots": [{"root": "gold-a", "score": score}],
            }
        ),
        encoding="utf-8",
    )


def test_summarizes_model_run_variation_for_compatible_evaluations(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_evaluation(first, score=0.4)
    _write_evaluation(second, score=0.6)

    assert stability_of([first, second]) == {
        "kind": "coding-evaluation-stability",
        "scope": "Repeated model executions only; this is not human inter-rater agreement.",
        "run_count": 2,
        "model_table": "models.evaluation-cli-gpt.yaml",
        "coding_profile": {"name": "single-coder-direct"},
        "evaluated_guidance": {"kind": "source", "hash": "guidance-a"},
        "roots": [
            {
                "name": "gold-a",
                "hash": "gold-hash-a",
                "documents": ["document.md"],
                "replicates": 2,
                "scores": [0.4, 0.6],
                "mean_f1": 0.5,
                "minimum_f1": 0.4,
                "maximum_f1": 0.6,
                "sample_stddev": pytest.approx(0.1414213562373095),
            }
        ],
    }


def test_refuses_to_combine_different_guidance(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_evaluation(first, score=0.4)
    _write_evaluation(second, score=0.6, guidance_hash="guidance-b")

    with pytest.raises(StabilityError, match="evaluated guidance"):
        stability_of([first, second])


def test_marks_legacy_source_tree_provenance_explicitly(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_evaluation(first, score=0.4, legacy_source_tree=True)
    _write_evaluation(second, score=0.6, legacy_source_tree=True)

    summary = stability_of([first, second])

    assert summary["evaluated_guidance"] == {
        "kind": "legacy-source-tree",
        "hash": "guidance-a",
    }


def test_cli_renders_a_stability_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_evaluation(first, score=0.4)
    _write_evaluation(second, score=0.6)

    main(["stability", str(first), str(second)])

    assert capsys.readouterr().out == (
        "Model-run stability\n"
        "Repeated model executions only; this is not human inter-rater agreement.\n"
        "Runs: 2; model table: models.evaluation-cli-gpt.yaml\n"
        "\n"
        "gold-a: mean F1 0.500; range 0.400–0.600; sample SD 0.141 across 2 runs\n"
    )
