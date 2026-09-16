from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from nabu_evals.gold import GoldRoot, _blocks, _without_blocks


def _totals(tp: float, fp: float, fn: float) -> dict[str, float]:
    precision = (
        1.0 if tp + fp == 0 and fn == 0 else 0.0 if tp + fp == 0 else tp / (tp + fp)
    )
    recall = (
        1.0 if tp + fn == 0 and fp == 0 else 0.0 if tp + fn == 0 else tp / (tp + fn)
    )
    f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _sentences(prose: str) -> list[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])(?=\s|$)|(?<=[。！？])", prose):
        end = match.end()
        left = start
        while left < end and prose[left].isspace():
            left += 1
        right = end
        while right > left and prose[right - 1].isspace():
            right -= 1
        if left < right:
            rows.append((left, right))
        start = end
    left = start
    while left < len(prose) and prose[left].isspace():
        left += 1
    right = len(prose)
    while right > left and prose[right - 1].isspace():
        right -= 1
    if left < right:
        rows.append((left, right))
    return rows


def _range_for_text(
    prose: str, rows: list[tuple[int, int]], text: str, occurrence: int
) -> dict[str, int] | None:
    if not text:
        return None
    offsets: list[tuple[int, int]] = []
    start = 0
    while start <= len(prose) - len(text):
        found = prose.find(text, start)
        if found == -1:
            break
        offsets.append((found, found + len(text)))
        start = found + 1
    ranges: list[dict[str, int]] = []
    for char_start, char_end in offsets:
        matching = [
            index
            for index, (row_start, row_end) in enumerate(rows)
            if row_end > char_start and row_start < char_end
        ]
        if matching:
            value = {"start": matching[0], "end": matching[-1]}
            if value not in ranges:
                ranges.append(value)
    return ranges[min(occurrence, len(ranges) - 1)] if ranges else None


def _findings(
    markdown: str, annotations: list[dict[str, Any]], side: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    prose = _without_blocks(markdown, "json-annotations")
    rows = _sentences(prose)
    findings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    occurrences: dict[tuple[str, str], int] = defaultdict(int)
    for index, annotation in enumerate(annotations):
        code = annotation.get("code")
        text = annotation.get("text")
        if not isinstance(code, str) or not code:
            errors.append(
                {
                    "side": side,
                    "index": index,
                    "code": None,
                    "type": "missing-code",
                    "text": text or "",
                    "candidateRanges": [],
                }
            )
            continue
        if not isinstance(text, str):
            errors.append(
                {
                    "side": side,
                    "index": index,
                    "code": code,
                    "type": "unresolved",
                    "text": "",
                    "candidateRanges": [],
                }
            )
            continue
        key = (code, text)
        span = _range_for_text(prose, rows, text, occurrences[key])
        occurrences[key] += 1
        if span is None:
            errors.append(
                {
                    "side": side,
                    "index": index,
                    "code": code,
                    "type": "unresolved",
                    "text": text,
                    "candidateRanges": [],
                }
            )
            continue
        findings.append({"index": index, "code": code, "text": text, "range": span})
    seen: set[tuple[str, int, int]] = set()
    duplicates = 0
    for finding in findings:
        key = (finding["code"], finding["range"]["start"], finding["range"]["end"])
        if key in seen:
            duplicates += 1
        seen.add(key)
    return findings, errors, duplicates


def _iou(first: dict[str, int], second: dict[str, int]) -> float:
    intersection = max(
        0, min(first["end"], second["end"]) - max(first["start"], second["start"]) + 1
    )
    union = max(first["end"], second["end"]) - min(first["start"], second["start"]) + 1
    return intersection / union


def _matches(
    predictions: list[dict[str, Any]], gold: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    source = 0
    prediction_start = 1
    gold_start = prediction_start + len(predictions)
    sink = gold_start + len(gold)
    graph: list[list[dict[str, Any]]] = [[] for _ in range(sink + 1)]

    def add_edge(
        origin: int,
        destination: int,
        cost: float,
        *,
        prediction: int | None = None,
        expected: int | None = None,
    ) -> None:
        forward = {
            "to": destination,
            "reverse": len(graph[destination]),
            "capacity": 1,
            "cost": cost,
            "prediction": prediction,
            "gold": expected,
        }
        reverse = {
            "to": origin,
            "reverse": len(graph[origin]),
            "capacity": 0,
            "cost": -cost,
        }
        graph[origin].append(forward)
        graph[destination].append(reverse)

    for index in range(len(predictions)):
        add_edge(source, prediction_start + index, 0)
    for index in range(len(gold)):
        add_edge(gold_start + index, sink, 0)
    for prediction_index, prediction in enumerate(predictions):
        for gold_index, expected in enumerate(gold):
            score = _iou(prediction["range"], expected["range"])
            if (threshold == 0 and score > 0) or (threshold > 0 and score >= threshold):
                add_edge(
                    prediction_start + prediction_index,
                    gold_start + gold_index,
                    -score,
                    prediction=prediction_index,
                    expected=gold_index,
                )

    while True:
        distance = [float("inf")] * len(graph)
        previous: list[tuple[int, int] | None] = [None] * len(graph)
        distance[source] = 0
        for _ in range(len(graph) - 1):
            changed = False
            for origin, edges in enumerate(graph):
                if distance[origin] == float("inf"):
                    continue
                for index, edge in enumerate(edges):
                    next_distance = distance[origin] + edge["cost"]
                    if (
                        edge["capacity"]
                        and next_distance < distance[edge["to"]] - 1e-12
                    ):
                        distance[edge["to"]] = next_distance
                        previous[edge["to"]] = (origin, index)
                        changed = True
            if not changed:
                break
        if distance[sink] >= -1e-12:
            break
        node = sink
        while node != source:
            step = previous[node]
            if step is None:
                raise RuntimeError("invalid matching path")
            origin, edge_index = step
            edge = graph[origin][edge_index]
            edge["capacity"] = 0
            graph[node][edge["reverse"]]["capacity"] = 1
            node = origin

    selected: list[dict[str, Any]] = []
    for edges in graph[prediction_start:gold_start]:
        for edge in edges:
            prediction_index = edge.get("prediction")
            gold_index = edge.get("gold")
            if (
                not isinstance(prediction_index, int)
                or not isinstance(gold_index, int)
                or edge["capacity"] != 0
            ):
                continue
            prediction = predictions[prediction_index]
            expected = gold[gold_index]
            score = _iou(prediction["range"], expected["range"])
            selected.append(
                {
                    "prediction": prediction,
                    "gold": expected,
                    "iou": score,
                    "exact": score == 1,
                }
            )
    return sorted(
        selected,
        key=lambda match: (
            match["prediction"]["index"],
            match["gold"]["index"],
            match["prediction"]["code"],
        ),
    )


def _annotations(markdown: str, label: str) -> list[dict[str, Any]]:
    blocks = _blocks(markdown, "json-annotations", Path(label))
    if len(blocks) != 1 or not isinstance(blocks[0].get("annotations"), list):
        raise ValueError(
            f"{label} must contain one schema-valid json-annotations block"
        )
    values = blocks[0]["annotations"]
    if not all(isinstance(value, dict) for value in values):
        raise ValueError(f"{label} annotations must be objects")
    return values


def compare_coding_documents(
    prediction_markdown: str, gold_markdown: str
) -> dict[str, Any]:
    if (
        _without_blocks(prediction_markdown, "json-annotations").strip()
        != _without_blocks(gold_markdown, "json-annotations").strip()
    ):
        raise ValueError("Prediction and gold document prose differ")
    prediction_annotations = _annotations(prediction_markdown, "Prediction")
    gold_annotations = _annotations(gold_markdown, "Gold")
    prediction, prediction_errors, prediction_duplicates = _findings(
        prediction_markdown, prediction_annotations, "prediction"
    )
    gold, gold_errors, gold_duplicates = _findings(
        gold_markdown, gold_annotations, "gold"
    )
    codes = sorted(
        {item["code"] for item in prediction + gold}
        | {item["code"] for item in prediction_errors + gold_errors if item["code"]}
    )
    by_code = lambda values, code: [value for value in values if value["code"] == code]
    matches = [
        match
        for code in codes
        for match in _matches(by_code(prediction, code), by_code(gold, code), 0)
    ]
    relaxed_matches = [
        match
        for code in codes
        for match in _matches(by_code(prediction, code), by_code(gold, code), 0.5)
    ]
    exact_matches = [
        match
        for code in codes
        for match in _matches(by_code(prediction, code), by_code(gold, code), 1)
    ]
    matched_prediction = {match["prediction"]["index"] for match in matches}
    matched_gold = {match["gold"]["index"] for match in matches}
    soft_tp = sum(match["iou"] for match in matches)
    predicted_count = len(prediction) + len(prediction_errors)
    gold_count = len(gold) + len(gold_errors)
    per_code = []
    for code in codes:
        code_matches = [
            match for match in matches if match["prediction"]["code"] == code
        ]
        tp = sum(match["iou"] for match in code_matches)
        predicted = len(by_code(prediction, code)) + len(
            by_code(prediction_errors, code)
        )
        expected = len(by_code(gold, code)) + len(by_code(gold_errors, code))
        per_code.append({"code": code, **_totals(tp, predicted - tp, expected - tp)})
    return {
        "matches": matches,
        "falsePositives": [
            item for item in prediction if item["index"] not in matched_prediction
        ],
        "falseNegatives": [item for item in gold if item["index"] not in matched_gold],
        "errors": prediction_errors + gold_errors,
        "duplicatePredictions": prediction_duplicates,
        "duplicateGold": gold_duplicates,
        "soft": _totals(soft_tp, predicted_count - soft_tp, gold_count - soft_tp),
        "relaxed": _totals(
            len(relaxed_matches),
            predicted_count - len(relaxed_matches),
            gold_count - len(relaxed_matches),
        ),
        "exact": _totals(
            len(exact_matches),
            predicted_count - len(exact_matches),
            gold_count - len(exact_matches),
        ),
        "meanIoU": None if not matches else soft_tp / len(matches),
        "perCode": per_code,
        "goldIsEmpty": not gold and not gold_errors,
    }


def score_coding_run(root: GoldRoot, raw: dict[str, Any]) -> dict[str, Any]:
    expected = {
        document.name: document
        for document in sorted((root.path / "corpus").glob("*.md"))
    }
    returned = {
        item.get("path"): item
        for item in raw.get("documents", [])
        if isinstance(item, dict)
    }
    documents: list[dict[str, Any]] = []
    for name, gold_path in expected.items():
        generated = returned.get(name)
        gold_markdown = gold_path.read_text(encoding="utf-8")
        gold_annotations = _annotations(gold_markdown, str(gold_path))
        if generated is None:
            documents.append(
                {
                    "name": name,
                    "status": "failed",
                    "annotationCount": None,
                    "goldAnnotationCount": len(gold_annotations),
                    "warnings": [],
                    "failures": ["frontend returned no result"],
                    "comparison": None,
                }
            )
            continue
        status = generated.get("status")
        failures = list(generated.get("failures", []))
        comparison: dict[str, Any] | None = None
        if status in {"success", "empty"}:
            try:
                comparison = compare_coding_documents(
                    str(generated.get("generatedMarkdown", "")), gold_markdown
                )
            except ValueError as error:
                status = "malformed"
                failures.append(str(error))
        documents.append(
            {
                "name": name,
                "status": status,
                "annotationCount": generated.get("annotationCount"),
                "goldAnnotationCount": len(gold_annotations),
                "warnings": list(generated.get("warnings", [])),
                "failures": failures,
                "comparison": comparison,
            }
        )
    outcomes = {
        status: sum(document["status"] == status for document in documents)
        for status in ("success", "empty", "partial", "failed", "malformed")
    }
    complete = all(document["status"] in {"success", "empty"} for document in documents)

    def aggregate(key: str) -> dict[str, float]:
        tp = sum(
            (document["comparison"] or {}).get(key, {}).get("tp", 0)
            for document in documents
        )
        fp = sum(
            (document["comparison"] or {}).get(key, {}).get("fp", 0)
            for document in documents
        )
        fn = sum(
            (document["comparison"] or {}).get(key, {}).get("fn", 0)
            for document in documents
        )
        return _totals(tp, fp, fn)

    invalid = _totals(
        0, 0, max(1, sum(document["goldAnnotationCount"] for document in documents))
    )
    requests = list(raw.get("requests", []))
    endpoints: set[str] = set()
    for request in requests:
        if not isinstance(request, dict):
            continue
        endpoint = request.get("endpoint")
        if isinstance(endpoint, str):
            endpoints.add(endpoint)
    return {
        "documents": documents,
        "outcomes": outcomes,
        "complete": complete,
        "soft": aggregate("soft") if complete else invalid,
        "relaxed": aggregate("relaxed") if complete else invalid,
        "exact": aggregate("exact") if complete else invalid,
        "perCode": [
            {"code": code, **aggregate_code(documents, code)} for code in root.code_ids
        ],
        "diagnostics": [],
        "requests": requests,
        "endpoints": sorted(endpoints),
        "latencyMs": raw.get("latencyMs", 0),
        "retries": raw.get("retries", 0),
    }


def aggregate_code(documents: list[dict[str, Any]], code: str) -> dict[str, float]:
    rows = [
        next(
            (
                score
                for score in (document["comparison"] or {}).get("perCode", [])
                if score["code"] == code
            ),
            None,
        )
        for document in documents
    ]
    tp = sum((row or {}).get("tp", 0) for row in rows)
    fp = sum((row or {}).get("fp", 0) for row in rows)
    fn = sum((row or {}).get("fn", 0) for row in rows)
    return _totals(tp, fp, fn)
