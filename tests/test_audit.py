from __future__ import annotations

import json
from pathlib import Path

from nabu_evals.audit import audit_directory, render_audit
from nabu_evals.scoring import compare_coding_documents


def _document(annotations: list[dict[str, str]]) -> str:
    return (
        "First sentence. Second sentence.\n\n```json-annotations\n"
        + json.dumps({"annotations": annotations})
        + "\n```\n"
    )


def test_audit_keeps_candidate_root_artifacts_separate(tmp_path: Path) -> None:
    gold = _document(
        [
            {
                "text": "Second sentence.",
                "reason": "gold",
                "code": "code-a",
                "actor": "gold",
            }
        ]
    )
    prediction = _document(
        [
            {
                "text": "Second sentence.",
                "reason": "prediction",
                "code": "code-b",
                "actor": "model",
            }
        ]
    )
    result_path = (
        tmp_path
        / "candidates"
        / "proposal-1"
        / "roots"
        / "root-1"
        / "attempt-1"
        / "results.json"
    )
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "complete": True,
                "outcomes": {"success": 1},
                "soft": {"f1": 0},
                "relaxed": {"f1": 0},
                "exact": {"f1": 0},
                "documents": [
                    {
                        "name": "document.md",
                        "status": "success",
                        "comparison": compare_coding_documents(prediction, gold),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result_path.with_name("coding-result.json").write_text(
        json.dumps(
            {
                "stages": [
                    {"stage": "candidates", "chunks": 1, "candidates": 2},
                    {
                        "stage": "voters",
                        "selections": {"voter-one": 1, "voter-two": 1},
                        "errors": 0,
                    },
                    {"stage": "consensus", "accepted": 1, "contested": 0},
                    {
                        "stage": "adjudication",
                        "contested": 0,
                        "accepted": 0,
                        "errors": 0,
                    },
                    {"stage": "decisions", "decisions": 1},
                ]
            }
        ),
        encoding="utf-8",
    )

    audit = audit_directory(tmp_path)

    assert audit["artifactCount"] == 1
    artifact = audit["artifacts"][0]
    assert artifact["candidate"] == "proposal-1"
    assert artifact["root"] == "root-1"
    assert artifact["alignment"]["wrongCodeAtOverlappingSpan"]["matches"] == 1
    assert artifact["alignment"]["residual"]["predictions"] == 0
    assert artifact["pipeline"]["stages"][0] == {
        "stage": "candidates",
        "chunks": 1,
        "candidates": 2,
    }
    assert (
        "does not decide whether a golden label is semantically right"
        in render_audit(audit)
    )
    assert "pipeline: candidates 2 across 1 chunks" in render_audit(audit)


def test_audit_requires_scored_result_artifacts(tmp_path: Path) -> None:
    try:
        audit_directory(tmp_path)
    except ValueError as error:
        assert "no results.json artifacts" in str(error)
    else:
        raise AssertionError("expected an audit input error")
