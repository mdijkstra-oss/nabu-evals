from __future__ import annotations

import json
from pathlib import Path

from nabu_evals.generate import generate_semeval_propaganda
from nabu_evals.gold import load_gold_root


def test_generates_a_normal_gold_root_from_semeval_training_data(
    tmp_path: Path,
) -> None:
    source = tmp_path / "datasets"
    articles = source / "train-articles"
    articles.mkdir(parents=True)
    article = "Headline\nFirst sentence 😀. Loaded phrase is here!\n"
    (articles / "article1.txt").write_text(article, encoding="utf-8")
    start = article.index("Loaded")
    end = start + len("Loaded phrase")
    second_start = article.index("here")
    second_end = second_start + len("here")
    (source / "train-task2-TC.labels").write_text(
        f"1\tLoaded_Language\t{start}\t{end}\n"
        f"1\tLoaded_Language\t{second_start}\t{second_end}\n",
        encoding="utf-8",
    )

    output = tmp_path / "gold"

    generate_semeval_propaganda(source, output)

    root = load_gold_root(output)
    assert (output / "framework.md").read_text(encoding="utf-8") == (
        "# PTC propaganda techniques\n\n"
        "Codebook of the SemEval-2020 Task 11 gold labels. Definitions verbatim "
        "from Da San Martino et al. (2019), Section 2 — the definitions the "
        "corpus annotators worked from.\n"
    )
    assert root.labels == 14
    assert root.document_count == 1
    assert root.annotations == 1
    assert len(list((output / "codes").glob("*.md"))) == 14
    callout = json.loads(
        (output / "codes" / "callout-2udgvv9z.md")
        .read_text(encoding="utf-8")
        .split("\n", 1)[1]
        .rsplit("\n```", 1)[0]
    )
    assert callout["title"] == "Loaded language"
    document = (output / "corpus" / "article1.md").read_text(encoding="utf-8")
    annotations = json.loads(
        document.split("```json-annotations\n", 1)[1].split("\n```", 1)[0]
    )
    assert annotations == {
        "annotations": [
            {
                "text": "Loaded phrase is here!",
                "reason": 'Gold (Loaded_Language) — span: "Loaded phrase", "here"',
                "code": "callout-2udgvv9z",
                "actor": "user",
            }
        ]
    }
