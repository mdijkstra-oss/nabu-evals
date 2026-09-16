from __future__ import annotations

import json
from pathlib import Path

import pytest

from nabu_evals.cli import main
from nabu_evals.generate import split_legacy_codebook
from nabu_evals.gold import GoldValidationError, coding_job_of, load_gold_root


def _root(
    path: Path, *, callout_ids: list[str], annotations: list[dict[str, str]]
) -> Path:
    (path / "corpus").mkdir(parents=True)
    (path / "codes").mkdir()
    (path / "framework.md").write_text("Shared coding guidance.\n", encoding="utf-8")
    for index, code in enumerate(callout_ids):
        (path / "codes" / f"code-{index}.md").write_text(
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
            + "\n```\n",
            encoding="utf-8",
        )
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


def test_exports_a_normal_coding_job_without_gold_annotations(tmp_path: Path) -> None:
    root = load_gold_root(
        _root(
            tmp_path / "gold", callout_ids=["known"], annotations=[_annotation("known")]
        )
    )

    assert coding_job_of(root) == {
        "framework": {"path": "framework.md", "markdown": "Shared coding guidance.\n"},
        "dimensions": [
            {
                "path": "codes/code-0.md",
                "markdown": (root.path / "codes" / "code-0.md").read_text(
                    encoding="utf-8"
                ),
            }
        ],
        "documents": [{"path": "a.md", "markdown": "One sentence.\n\n"}],
    }


def test_splits_a_legacy_codebook_into_normal_coding_sources(tmp_path: Path) -> None:
    root = tmp_path / "gold"
    root.mkdir()
    (root / "codebook.md").write_text(
        "# Framework\n\n```json-callout\n"
        + json.dumps(
            {
                "id": "known",
                "type": "codebook-code",
                "title": "Known",
                "content": "A definition.",
                "color": "blue",
                "collapsed": False,
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )

    split_legacy_codebook(root)

    assert not (root / "codebook.md").exists()
    assert (root / "framework.md").read_text(encoding="utf-8") == "# Framework\n\n"
    assert "known" in (root / "codes" / "known.md").read_text(encoding="utf-8")


def test_runs_the_codebook_migration_through_the_generator_cli(tmp_path: Path) -> None:
    root = tmp_path / "gold"
    root.mkdir()
    (root / "codebook.md").write_text(
        "```json-callout\n"
        + json.dumps(
            {
                "id": "known",
                "type": "codebook-code",
                "title": "Known",
                "content": "A definition.",
                "color": "blue",
                "collapsed": False,
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )

    main(["generate", "migrate-codebook", str(root)])

    assert (root / "framework.md").is_file()
