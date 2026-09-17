from __future__ import annotations

import json

from nabu_evals.scoring import compare_coding_documents, diagnose_comparison


def _document(
    annotations: list[dict[str, str]], prose: str = "First sentence. Second sentence."
) -> str:
    return (
        prose
        + "\n\n```json-annotations\n"
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


def test_resolves_frontend_normalized_annotation_text_against_markdown_source() -> None:
    source = "I offered *-hugs-*."
    gold = _document(
        [
            {
                "text": source,
                "reason": "gold",
                "code": "code-a",
                "actor": "gold",
            }
        ],
        source,
    )
    prediction = _document(
        [
            {
                "text": "I offered -hugs-.",
                "reason": "frontend-normalized",
                "code": "code-a",
                "actor": "model",
            }
        ],
        source,
    )

    comparison = compare_coding_documents(prediction, gold)

    assert comparison["errors"] == []
    assert comparison["soft"]["f1"] == 1


def test_diagnoses_a_wrong_code_at_the_correct_span() -> None:
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

    diagnosis = diagnose_comparison(compare_coding_documents(prediction, gold))

    assert diagnosis["sameCode"] == {
        "matches": 0,
        "exact": 0,
        "relaxed": 0,
        "weak": 0,
        "totalIou": 0,
    }
    assert diagnosis["wrongCodeAtOverlappingSpan"] == {
        "matches": 1,
        "exact": 1,
        "relaxed": 1,
        "weak": 0,
        "totalIou": 1,
    }
    assert diagnosis["residual"] == {
        "predictions": 0,
        "gold": 0,
        "predictionResolverErrors": 0,
        "goldResolverErrors": 0,
    }
    assert diagnosis["codePresence"] == {
        "tp": 0,
        "fp": 1,
        "fn": 1,
        "precision": 0,
        "recall": 0,
        "f1": 0,
    }


def test_diagnoses_a_same_code_span_boundary_difference() -> None:
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

    diagnosis = diagnose_comparison(compare_coding_documents(prediction, gold))

    assert diagnosis["sameCode"] == {
        "matches": 1,
        "exact": 0,
        "relaxed": 1,
        "weak": 0,
        "totalIou": 0.5,
    }
    assert diagnosis["wrongCodeAtOverlappingSpan"]["matches"] == 0
    assert diagnosis["residual"]["predictions"] == 0
    assert diagnosis["residual"]["gold"] == 0


def test_diagnosis_keeps_unresolved_output_separate_from_span_errors() -> None:
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
                "text": "Not in the document.",
                "reason": "prediction",
                "code": "code-a",
                "actor": "model",
            }
        ]
    )

    diagnosis = diagnose_comparison(compare_coding_documents(prediction, gold))

    assert diagnosis["sameCode"]["matches"] == 0
    assert diagnosis["wrongCodeAtOverlappingSpan"]["matches"] == 0
    assert diagnosis["residual"] == {
        "predictions": 0,
        "gold": 1,
        "predictionResolverErrors": 1,
        "goldResolverErrors": 0,
    }
