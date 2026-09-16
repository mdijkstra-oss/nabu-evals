from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from nabu_evals.generators.epitome import generate_epitome
from nabu_evals.gold import load_gold_root


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _callout_id(label: str) -> str:
    digest = hashlib.sha256(f"epitome:{label}".encode()).hexdigest()
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    value = int(digest[2:16], 16)
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = alphabet[remainder] + encoded
    return f"callout-{int(digest[:2], 16) % 10}{encoded.rjust(7, '0')[:7]}"


def test_generates_a_normal_gold_root_from_epitome_csvs(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    shared = {
        "sp_id": "seeker-1",
        "rp_id": "response-1",
        "seeker_post": "I am afraid of tomorrow.",
        "response_post": "I am so sorry you are hurting. I understand how scary this is.",
    }
    _write_rows(
        dataset / "emotional-reactions-reddit.csv",
        [{**shared, "level": "2", "rationales": "so sorry"}],
    )
    _write_rows(
        dataset / "interpretations-reddit.csv",
        [{**shared, "level": "1", "rationales": "I understand"}],
    )
    _write_rows(
        dataset / "explorations-reddit.csv",
        [{**shared, "level": "0", "rationales": ""}],
    )
    output = tmp_path / "epitome-gold"

    summary = generate_epitome(dataset, output)

    strong = _callout_id("emotional-reactions-strong")
    weak = _callout_id("interpretations-weak")
    document = (output / "corpus" / "seeker-1-response-1.md").read_text(
        encoding="utf-8"
    )
    annotations = json.loads(
        document.split("```json-annotations\n", 1)[1].split("\n```", 1)[0]
    )["annotations"]
    assert summary == {
        "codes": 6,
        "exchanges": 1,
        "annotations": 2,
        "unanchorable_rationales": 0,
        "labels_without_rationale": 0,
        "level_conflicts": 0,
    }
    assert (output / "framework.md").is_file()
    assert len(list((output / "codes").glob("*.md"))) == 6
    assert annotations == [
        {
            "text": "I am so sorry you are hurting.",
            "reason": 'Gold (Emotional reactions, strong) — rationale: "so sorry"',
            "code": strong,
            "actor": "user",
        },
        {
            "text": "I understand how scary this is.",
            "reason": 'Gold (Interpretations, weak) — rationale: "I understand"',
            "code": weak,
            "actor": "user",
        },
    ]
    root = load_gold_root(output)
    assert (root.document_count, root.labels, root.annotations) == (1, 6, 2)
