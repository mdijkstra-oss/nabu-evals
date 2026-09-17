from __future__ import annotations

import json
from pathlib import Path

import pytest

from nabu_evals.cli import _evaluate, _parser
from nabu_evals.optimizer import (
    DEFAULT_MODEL_TABLE,
    EVALUATION_MODEL_TABLES,
)


def test_evaluation_defaults_to_a_cli_backed_gpt_table() -> None:
    assert DEFAULT_MODEL_TABLE == "models.evaluation-cli-gpt.yaml"
    assert EVALUATION_MODEL_TABLES == (
        "models.evaluation-cli-gpt.yaml",
        "models.evaluation-cli-gpt-terra-coder-low.yaml",
        "models.evaluation-cli-gpt-terra-coder-high.yaml",
        "models.evaluation-cli-gpt-sol-coder-medium.yaml",
        "models.evaluation-cli-gpt-sol-adjudicator-high.yaml",
        "models.evaluation-cli-claude.yaml",
        "models.evaluation-cli-mixed.yaml",
    )


def test_cli_refuses_a_provider_api_model_table_for_evaluation() -> None:
    parser = _parser()
    common = [
        "optimize",
        "gold",
        "--frontend",
        "frontend",
        "--prompts",
        "prompts",
        "--output",
        "output",
    ]

    assert parser.parse_args(common).model_table == DEFAULT_MODEL_TABLE
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--model-table", "models.openai.yaml"])


def test_evaluate_accepts_an_explicit_coverage_probe_size() -> None:
    args = _parser().parse_args(
        [
            "evaluate",
            "gold",
            "--frontend",
            "frontend",
            "--prompts",
            "prompts",
            "--output",
            "output",
            "--coverage-probe-documents",
            "1",
        ]
    )

    assert args.coverage_probe_documents == 1


def test_evaluate_accepts_a_supplied_guidance_file() -> None:
    args = _parser().parse_args(
        [
            "evaluate",
            "gold",
            "--frontend",
            "frontend",
            "--prompts",
            "prompts",
            "--output",
            "output",
            "--guidance-file",
            "candidate.md",
        ]
    )

    assert args.guidance_file == Path("candidate.md")


def test_evaluate_projects_the_requested_coverage_probe_before_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "gold"
    (root / "codes").mkdir(parents=True)
    (root / "corpus").mkdir()
    (root / "framework.md").write_text("Framework\n", encoding="utf-8")
    (root / "codes" / "code.md").write_text(
        "```json-callout\n"
        + json.dumps(
            {
                "id": "code",
                "type": "codebook-code",
                "title": "Code",
                "content": "Find evidence.",
                "color": "blue",
                "collapsed": False,
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )
    for name in ("a.md", "b.md"):
        (root / "corpus" / name).write_text(
            f"{name}\n\n```json-annotations\n"
            + json.dumps(
                {
                    "annotations": [
                        {
                            "text": name,
                            "reason": "gold",
                            "code": "code",
                            "actor": "gold",
                        }
                    ]
                }
            )
            + "\n```\n",
            encoding="utf-8",
        )
    captured: dict[str, object] = {}

    def fake_run_evaluation(
        settings: object, roots: object, guidance: str | None = None
    ) -> dict[str, object]:
        captured["roots"] = roots
        captured["guidance"] = guidance
        return {"kind": "fixed-coding-evaluation"}

    monkeypatch.setattr("nabu_evals.cli.run_evaluation", fake_run_evaluation)
    candidate = tmp_path / "candidate.md"
    candidate.write_text("Candidate.\n", encoding="utf-8")
    args = _parser().parse_args(
        [
            "evaluate",
            str(root),
            "--frontend",
            str(tmp_path / "frontend"),
            "--prompts",
            str(tmp_path / "prompts"),
            "--output",
            str(tmp_path / "output"),
            "--coverage-probe-documents",
            "1",
            "--guidance-file",
            str(candidate),
        ]
    )

    _evaluate(args)

    selected = captured["roots"]
    assert isinstance(selected, list)
    assert selected[0].document_count == 1
    assert selected[0].selection == "coverage-probe-1"
    assert captured["guidance"] == "Candidate.\n"
    manifest = json.loads((tmp_path / "output" / "run.json").read_text())
    assert manifest["roots"][0]["document_count"] == 1
    assert manifest["guidance_file"] == str(candidate)
