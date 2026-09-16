from __future__ import annotations

import json
from pathlib import Path

import pytest

from nabu_evals.gold import GoldValidationError, load_gold_root


def _root(
    path: Path, *, callout_ids: list[str], annotations: list[dict[str, str]]
) -> Path:
    (path / "corpus").mkdir(parents=True)
    callouts = "\n".join(
        "```json-callout\n"
        + json.dumps(
            {
                "id": code,
                "type": "codebook-code",
                "title": code,
                "content": "A general definition.",
                "color": "blue",
                "collapsed": False,
            }
        )
        + "\n```"
        for code in callout_ids
    )
    (path / "codebook.md").write_text(callouts, encoding="utf-8")
    (path / "corpus" / "a.md").write_text(
        "One sentence.\n\n```json-annotations\n"
        + json.dumps({"annotations": annotations})
        + "\n```\n",
        encoding="utf-8",
    )
    return path


def _annotation(code: str) -> dict[str, str]:
    return {"text": "One sentence.", "reason": "because", "code": code, "actor": "gold"}


def test_rejects_unknown_gold_code(tmp_path: Path) -> None:
    root = _root(
        tmp_path / "gold", callout_ids=["known"], annotations=[_annotation("unknown")]
    )
    with pytest.raises(GoldValidationError, match="unknown gold code"):
        load_gold_root(root)


def test_rejects_duplicate_callout_ids_and_all_negative_roots(tmp_path: Path) -> None:
    duplicate = _root(
        tmp_path / "duplicate",
        callout_ids=["same", "same"],
        annotations=[_annotation("same")],
    )
    with pytest.raises(GoldValidationError, match="duplicate callout IDs"):
        load_gold_root(duplicate)
    negative = _root(tmp_path / "negative", callout_ids=["known"], annotations=[])
    with pytest.raises(GoldValidationError, match="positive gold annotation"):
        load_gold_root(negative)


def test_records_negative_documents_without_sampling(tmp_path: Path) -> None:
    root_path = _root(
        tmp_path / "gold", callout_ids=["known"], annotations=[_annotation("known")]
    )
    (root_path / "corpus" / "negative.md").write_text(
        'Nothing.\n\n```json-annotations\n{"annotations": []}\n```\n', encoding="utf-8"
    )
    root = load_gold_root(root_path)
    assert root.document_count == 2
    assert root.annotations == 1
    assert root.negatives == 1
