from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from nabu_evals.gold import load_gold_root
from nabu_evals.runtime import CandidateRuntime, RuntimeFailure, RuntimeSettings
from nabu_evals.target import QualCodingTarget, coding_profile


def _target(tmp_path: Path) -> QualCodingTarget:
    root_path = tmp_path / "gold"
    (root_path / "corpus").mkdir(parents=True)
    (root_path / "codes").mkdir()
    (root_path / "framework.md").write_text(
        "Shared coding guidance.\n", encoding="utf-8"
    )
    (root_path / "codes" / "secret-callout.md").write_text(
        "```json-callout\n"
        + json.dumps(
            {
                "id": "secret-callout",
                "type": "codebook-code",
                "title": "Secret",
                "content": "This definition has twelve distinct words that must never be copied into proposed reusable guidance verbatim.",
                "color": "blue",
                "collapsed": False,
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )
    body = "These are twelve corpus words that must never be copied into a reusable proposal exactly today."
    (root_path / "corpus" / "secret-document.md").write_text(
        body
        + "\n\n```json-annotations\n"
        + json.dumps(
            {
                "annotations": [
                    {
                        "text": body,
                        "reason": "gold",
                        "code": "secret-callout",
                        "actor": "gold",
                    }
                ]
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )
    root = load_gold_root(root_path)
    runtime = RuntimeSettings(
        prompts=tmp_path,
        output=tmp_path / "output",
        chancery_bin="chancery",
        dragoman_bin="dragoman",
        model_table="models.yaml",
        bridge_url="http://127.0.0.1:8082",
    )
    return QualCodingTarget(
        roots=[root],
        runtime=runtime,
        frontend=tmp_path,
        npm_bin="npm",
        dragoman_port=1,
        per_root_timeout=1,
        max_frontend_invocations=1,
        max_coding_requests=1,
        total_deadline=time.monotonic() + 10,
        baseline="Seed guidance.",
    )


def test_rejects_proposal_leakage_and_seed_repetition(tmp_path: Path) -> None:
    target = _target(tmp_path)
    assert target.validate_candidate("Seed guidance.") == [
        "proposal is identical to the seed"
    ]
    assert "callout ID" in " ".join(target.validate_candidate("Use secret-callout."))
    assert "corpus filename" in " ".join(
        target.validate_candidate("Use secret-document.md as a reference.")
    )
    leaked = "This definition has twelve distinct words that must never be copied into proposed reusable guidance verbatim."
    assert "coding-source/corpus passage" in " ".join(target.validate_candidate(leaked))


def test_accepts_generic_guidance(tmp_path: Path) -> None:
    target = _target(tmp_path)
    assert (
        target.validate_candidate(
            "Judge each definition independently, prefer precise complete spans, and abstain when evidence is insufficient."
        )
        == []
    )


def test_rejects_partial_root_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _target(tmp_path)
    calls = 0

    def coding_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        output = Path(command[command.index("--output") + 1])
        output.write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "path": "secret-document.md",
                            "status": "partial",
                            "annotationCount": None,
                            "warnings": ["LLM request failed: 503"],
                            "failures": [],
                        }
                    ],
                    "requests": [{"endpoint": "/deep-analysis-filter.voter-one"}],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("nabu_evals.target.subprocess.run", coding_run)
    runtime = CandidateRuntime(
        target.runtime, "Seed guidance.", "digest", "baseline", 1
    )

    with pytest.raises(RuntimeFailure, match="partial"):
        target._run_root(
            "Seed guidance.",
            "digest",
            "baseline",
            runtime,
            target.roots[0],
            0,
        )

    assert calls == 1


def test_rejects_unresolved_annotation_spans_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _target(tmp_path)
    calls = 0
    source = (target.roots[0].path / "corpus" / "secret-document.md").read_text(
        encoding="utf-8"
    )
    prose = source.partition("```json-annotations")[0].rstrip()

    def coding_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        output = Path(command[command.index("--output") + 1])
        output.write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "path": "secret-document.md",
                            "status": "success",
                            "annotationCount": 1,
                            "warnings": [],
                            "failures": [],
                            "generatedMarkdown": (
                                prose
                                + "\n\n```json-annotations\n"
                                + json.dumps(
                                    {
                                        "annotations": [
                                            {
                                                "text": "Not in this document.",
                                                "reason": "invalid",
                                                "code": "secret-callout",
                                                "actor": "model",
                                            }
                                        ]
                                    }
                                )
                                + "\n```\n"
                            ),
                        }
                    ],
                    "requests": [{"endpoint": "/deep-analysis-filter.voter-one"}],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("nabu_evals.target.subprocess.run", coding_run)
    runtime = CandidateRuntime(
        target.runtime, "Seed guidance.", "digest", "baseline", 1
    )

    with pytest.raises(RuntimeFailure, match="unresolved annotation span"):
        target._run_root(
            "Seed guidance.",
            "digest",
            "baseline",
            runtime,
            target.roots[0],
            0,
        )

    assert calls == 1


def test_coding_profiles_make_the_evaluation_boundary_explicit() -> None:
    direct = coding_profile("single-coder-direct")
    consensus = coding_profile("two-voter-adjudicated")

    assert direct.passthrough == ("retrieval", "semantic-filter")
    assert direct.coders == ("voter-one",)
    assert direct.adjudicate is False
    assert direct.allowed_endpoints == frozenset({"/deep-analysis-filter.voter-one"})
    assert consensus.passthrough == ("retrieval", "semantic-filter")
    assert consensus.coders == ("voter-one", "voter-two")
    assert consensus.adjudicate is True
    assert consensus.allowed_endpoints == frozenset(
        {
            "/deep-analysis-filter.voter-one",
            "/deep-analysis-filter.voter-two",
            "/deep-analysis-adjudicate",
        }
    )
