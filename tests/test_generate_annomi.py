from __future__ import annotations

import csv
import json
from pathlib import Path

from nabu_evals.annomi import generate_annomi
from nabu_evals.gold import load_gold_root


def test_generates_normal_gold_sources_from_annomi_full_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "annomi"
    data_dir.mkdir()
    headers = [
        "transcript_id",
        "utterance_id",
        "interlocutor",
        "utterance_text",
        "mi_quality",
        "topic",
        "video_title",
        "question_exists",
        "question_subtype",
        "reflection_exists",
        "reflection_subtype",
        "therapist_input_exists",
        "therapist_input_subtype",
        "client_talk_type",
    ]
    therapist = {
        "transcript_id": "7",
        "utterance_id": "1",
        "interlocutor": "therapist",
        "utterance_text": "What would you like to change?",
        "mi_quality": "high",
        "topic": "alcohol",
        "video_title": "Example",
        "question_exists": "True",
        "question_subtype": "open",
        "reflection_exists": "True",
        "reflection_subtype": "simple",
        "therapist_input_exists": "False",
        "therapist_input_subtype": "",
        "client_talk_type": "neutral",
    }
    client = {
        **therapist,
        "utterance_id": "2",
        "interlocutor": "client",
        "utterance_text": "I want to stop drinking.",
        "question_exists": "False",
        "question_subtype": "",
        "reflection_exists": "False",
        "reflection_subtype": "",
        "client_talk_type": "change",
    }
    with (data_dir / "AnnoMI-full.csv").open(
        "w", newline="", encoding="utf-8"
    ) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows([therapist, therapist, therapist, client, client, client])

    output_dir = tmp_path / "gold"
    generate_annomi(data_dir, output_dir)

    root = load_gold_root(output_dir)
    assert root.labels == 10
    assert root.document_count == 1
    assert root.annotations == 3
    assert (output_dir / "framework.md").is_file()
    assert len(list((output_dir / "codes").glob("*.md"))) == 10
    document = (output_dir / "corpus" / "transcript-007.md").read_text(encoding="utf-8")
    assert "Therapist: What would you like to change?" in document
    annotations = json.loads(
        document.split("```json-annotations\n", 1)[1].split("\n```", 1)[0]
    )["annotations"]
    assert {annotation["reason"] for annotation in annotations} == {
        "Gold (open question) — 3/3 annotators",
        "Gold (simple reflection) — 3/3 annotators",
        "Gold (change talk) — 3/3 annotators",
    }
