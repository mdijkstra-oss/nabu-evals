from __future__ import annotations

import json
import time
from pathlib import Path

from nabu_evals.gold import load_gold_root
from nabu_evals.runtime import RuntimeSettings
from nabu_evals.target import QualCodingTarget


def _target(tmp_path: Path) -> QualCodingTarget:
    root_path = tmp_path / "gold"
    (root_path / "corpus").mkdir(parents=True)
    (root_path / "codebook.md").write_text(
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
    assert "codebook/corpus passage" in " ".join(target.validate_candidate(leaked))


def test_accepts_generic_guidance(tmp_path: Path) -> None:
    target = _target(tmp_path)
    assert (
        target.validate_candidate(
            "Judge each definition independently, prefer precise complete spans, and abstain when evidence is insufficient."
        )
        == []
    )
