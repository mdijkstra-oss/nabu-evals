from __future__ import annotations

import json

from nabu_evals.scoring import compare_coding_documents


def _document(annotations: list[dict[str, str]]) -> str:
    return (
        "First sentence. Second sentence.\n\n```json-annotations\n"
        + json.dumps({"annotations": annotations})
        + "\n```\n"
    )


def test_scores_sentence_overlap_as_soft_f1() -> None:
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
                "text": "First sentence. Second sentence.",
                "reason": "prediction",
                "code": "code-a",
                "actor": "model",
            }
        ]
    )

    comparison = compare_coding_documents(prediction, gold)

    assert comparison["soft"]["f1"] == 0.5
    assert comparison["relaxed"]["f1"] == 1
    assert comparison["exact"]["f1"] == 0
