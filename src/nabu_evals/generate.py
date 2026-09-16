from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TypedDict

from nabu_evals.gold import _FENCE, GoldValidationError, _blocks, _without_blocks


def _format_block(language: str, value: object) -> str:
    return f"```{language}\n{json.dumps(value, indent=2)}\n```\n"


def split_legacy_codebook(root: Path) -> None:
    """Replace a combined codebook.md with normal framework and code source files."""
    root = root.expanduser().resolve()
    legacy = root / "codebook.md"
    framework = root / "framework.md"
    codes = root / "codes"
    if not legacy.is_file():
        raise GoldValidationError(f"{root}: missing codebook.md")
    if framework.exists() or codes.exists():
        raise GoldValidationError(f"{root}: framework.md or codes already exists")
    markdown = legacy.read_text(encoding="utf-8")
    callouts = _blocks(markdown, "json-callout", legacy)
    fenced_callouts = [
        match
        for match in _FENCE.finditer(markdown)
        if match.group("language") == "json-callout"
    ]
    if len(callouts) != len(fenced_callouts) or not callouts:
        raise GoldValidationError(
            f"{legacy}: expected schema-valid json-callout blocks"
        )
    ids: list[str] = []
    for callout in callouts:
        identifier = callout.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise GoldValidationError(f"{legacy}: callout has no non-empty id")
        ids.append(identifier)
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if duplicates:
        raise GoldValidationError(
            f"{legacy}: duplicate callout IDs: {', '.join(duplicates)}"
        )
    framework.write_text(_without_blocks(markdown, "json-callout"), encoding="utf-8")
    codes.mkdir()
    for callout in callouts:
        (codes / f"{callout['id']}.md").write_text(
            _format_block("json-callout", callout), encoding="utf-8"
        )
    legacy.unlink()


class _SemEvalCode(TypedDict):
    title: str
    color: str
    definition: str


_SEMEVAL_CODES: dict[str, _SemEvalCode] = {
    "Loaded_Language": {
        "title": "Loaded language",
        "color": "tomato",
        "definition": 'Using words/phrases with strong emotional implications (positive or negative) to influence an audience.\n\nEx.: "[...] a lone lawmaker’s childish shouting."',
    },
    "Name_Calling,Labeling": {
        "title": "Name calling or labeling",
        "color": "red",
        "definition": 'Labeling the object of the propaganda campaign as either something the target audience fears, hates, finds undesirable or otherwise loves or praises.\n\nEx.: "Republican congressweasels", "Bush the Lesser."',
    },
    "Repetition": {
        "title": "Repetition",
        "color": "pink",
        "definition": "Repeating the same message over and over again, so that the audience will eventually accept it.",
    },
    "Exaggeration,Minimisation": {
        "title": "Exaggeration or minimization",
        "color": "plum",
        "definition": 'Either representing something in an excessive manner: making things larger, better, worse (e.g., "the best of the best", "quality guaranteed") or making something seem less important or smaller than it actually is, e.g., saying that an insult was just a joke.\n\nEx.: "Democrats bolted as soon as Trump’s speech ended in an apparent effort to signal they can’t even stomach being in the same room as the president"; "I was not fighting with her; we were just playing."',
    },
    "Doubt": {
        "title": "Doubt",
        "color": "purple",
        "definition": 'Questioning the credibility of someone or something.\n\nEx.: A candidate says about his opponent: "Is he ready to be the Mayor?"',
    },
    "Appeal_to_fear-prejudice": {
        "title": "Appeal to fear/prejudice",
        "color": "violet",
        "definition": 'Seeking to build support for an idea by instilling anxiety and/or panic in the population towards an alternative, possibly based on preconceived judgments.\n\nEx.: "stop those refugees; they are terrorists."',
    },
    "Flag-Waving": {
        "title": "Flag-waving",
        "color": "indigo",
        "definition": 'Playing on strong national feeling (or with respect to a group, e.g., race, gender, political preference) to justify or promote an action or idea.\n\nEx.: "entering this war will make us have a better future in our country."',
    },
    "Causal_Oversimplification": {
        "title": "Causal oversimplification",
        "color": "blue",
        "definition": 'Assuming one cause when there are multiple causes behind an issue. We include scapegoating as well: the transfer of the blame to one person or group of people without investigating the complexities of an issue.\n\nEx.: "If France had not declared war on Germany, World War II would have never happened."',
    },
    "Slogans": {
        "title": "Slogans",
        "color": "cyan",
        "definition": 'A brief and striking phrase that may include labeling and stereotyping. Slogans tend to act as emotional appeals.\n\nEx.: "Make America great again!"',
    },
    "Appeal_to_Authority": {
        "title": "Appeal to authority",
        "color": "teal",
        "definition": "Stating that a claim is true simply because a valid authority/expert on the issue supports it, without any other supporting evidence. We include the special case where the reference is not an authority/expert, although it is referred to as testimonial in the literature.",
    },
    "Black-and-White_Fallacy": {
        "title": "Black-and-white fallacy, dictatorship",
        "color": "jade",
        "definition": 'Presenting two alternative options as the only possibilities, when in fact more possibilities exist. As an extreme case, telling the audience exactly what actions to take, eliminating any other possible choice (dictatorship).\n\nEx.: "You must be a Republican or Democrat; you are not a Democrat. Therefore, you must be a Republican"; "There is no alternative to war."',
    },
    "Thought-terminating_Cliches": {
        "title": "Thought-terminating cliché",
        "color": "green",
        "definition": 'Words or phrases that discourage critical thought and meaningful discussion about a given topic. They are typically short, generic sentences that offer seemingly simple answers to complex questions or that distract attention away from other lines of thought.\n\nEx.: "it is what it is"; "you cannot judge it without experiencing it"; "it’s common sense"; "nothing is permanent except change"; "better late than never"; "mind your own business"; "nobody’s perfect"; "it doesn’t matter"; "you can’t change human nature."',
    },
    "Whataboutism,Straw_Men,Red_Herring": {
        "title": "Whataboutism, straw man, red herring",
        "color": "amber",
        "definition": 'Whataboutism: Discredit an opponent’s position by charging them with hypocrisy without directly disproving their argument. For example, mentioning an event that discredits the opponent: "What about ...?"\n\nStraw man: When an opponent’s proposition is substituted with a similar one which is then refuted in place of the original.\n\nRed herring: Introducing irrelevant material to the issue being discussed, so that everyone’s attention is diverted away from the points made. Those subjected to a red herring argument are led away from the issue that had been the focus of the discussion and urged to follow an observation or claim that may be associated with the original claim, but is not highly relevant to the issue in dispute.\n\nEx.: "You may claim that the death penalty is an ineffective deterrent against crime — but what about the victims of crime? How do you think surviving family members feel when they see the man who murdered their son kept in prison at their expense? Is it right that they should pay for their son’s murderer to be fed and housed?"',
    },
    "Bandwagon,Reductio_ad_hitlerum": {
        "title": "Bandwagon, reductio ad Hitlerum",
        "color": "orange",
        "definition": 'Bandwagon: Attempting to persuade the target audience to join in and take the course of action because "everyone else is taking the same action".\n\nReductio ad Hitlerum: Persuading an audience to disapprove an action or idea by suggesting that the idea is popular with groups hated in contempt by the target audience. It can refer to any person or concept with a negative connotation.\n\nEx.: "Would you vote for Clinton as president? 57% say yes."; "Only one kind of person can think this way: a communist."',
    },
}


def _semeval_callout_id(label: str) -> str:
    digest = hashlib.sha256(f"ptc:{label}".encode()).hexdigest()
    digit = int(digest[:2], 16) % 10
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    value = int(digest[2:16], 16)
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = alphabet[remainder] + encoded
    return f"callout-{digit}{encoded.rjust(7, '0')[:7]}"


def _sentence_ranges(prose: str) -> list[tuple[int, int]]:
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


def _semeval_block(language: str, value: object) -> str:
    return f"```{language}\n{json.dumps(value, indent='\t', ensure_ascii=False)}\n```\n"


def _semeval_reason(label: str, spans: list[str]) -> str:
    quoted = [
        json.dumps(re.sub(r"\s+", " ", span)[:120], ensure_ascii=False)
        for span in spans
    ]
    return f"Gold ({label}) — span: {', '.join(quoted)}"


def generate_semeval_propaganda(data_dir: Path, output_dir: Path) -> None:
    """Generate a normal coding gold root from SemEval-2020 Task 11 PTC v2."""
    source = data_dir.expanduser().resolve()
    output = output_dir.expanduser().resolve()
    articles_dir = source / "train-articles"
    label_file = source / "train-task2-TC.labels"
    articles = {
        file.name.removeprefix("article").removesuffix(".txt"): file.read_text(
            encoding="utf-8"
        )
        for file in sorted(articles_dir.iterdir())
        if file.is_file()
    }
    labels = [
        line for line in label_file.read_text(encoding="utf-8").splitlines() if line
    ]

    output.mkdir(parents=True, exist_ok=True)
    codes = output / "codes"
    corpus = output / "corpus"
    codes.mkdir(parents=True, exist_ok=True)
    corpus.mkdir(parents=True, exist_ok=True)
    framework = (
        "# PTC propaganda techniques\n\n"
        "Codebook of the SemEval-2020 Task 11 gold labels. Definitions verbatim "
        "from Da San Martino et al. (2019), Section 2 — the definitions the corpus "
        "annotators worked from.\n"
    )
    (output / "framework.md").write_text(framework, encoding="utf-8")
    for label, code in _SEMEVAL_CODES.items():
        callout = {
            "id": _semeval_callout_id(label),
            "type": "codebook-code",
            "title": code["title"],
            "color": code["color"],
            "collapsed": False,
            "content": code["definition"],
        }
        (codes / f"{callout['id']}.md").write_text(
            _semeval_block("json-callout", callout), encoding="utf-8"
        )

    gold_by_article: dict[str, list[tuple[str, str, int, int, str]]] = {}
    for line in labels:
        article, label, start_text, end_text = line.split("\t")
        if label not in _SEMEVAL_CODES:
            raise GoldValidationError(f"unknown SemEval gold label {label}")
        text = articles.get(article)
        if text is None:
            raise GoldValidationError(f"labels reference missing article {article}")
        start, end = int(start_text), int(end_text)
        if start < 0 or end > len(text) or start > end:
            raise GoldValidationError(
                f"offset out of range in article {article}: {start_text}-{end_text}"
            )
        span = text[start:end]
        if not span.strip():
            raise GoldValidationError(
                f"gold span sliced to empty text in article {article}: {start_text}-{end_text}"
            )
        matching = [
            row for row in _sentence_ranges(text) if row[1] > start and row[0] < end
        ]
        if not matching:
            raise GoldValidationError(
                f"gold span outside any sentence in article {article} at {start}-{end}"
            )
        sentence_start, sentence_end = matching[0][0], matching[-1][1]
        gold_by_article.setdefault(article, []).append(
            (
                label,
                span,
                sentence_start,
                sentence_end,
                text[sentence_start:sentence_end],
            )
        )

    for article, text in articles.items():
        title = text.split("\n", 1)[0].strip()
        attributes = {
            "type": "news-article",
            "source": "SemEval-2020 Task 11 (PTC corpus)",
            "subject": title if len(title) <= 80 else f"{title[:77]}...",
        }
        grouped: dict[tuple[str, int, int], tuple[str, int, int, str, list[str]]] = {}
        for label, span, sentence_start, sentence_end, sentence in gold_by_article.get(
            article, []
        ):
            key = (label, sentence_start, sentence_end)
            if key not in grouped:
                grouped[key] = (label, sentence_start, sentence_end, sentence, [span])
            else:
                grouped[key][4].append(span)
        annotations = [
            {
                "text": sentence,
                "reason": _semeval_reason(label, spans),
                "code": _semeval_callout_id(label),
                "actor": "user",
            }
            for label, _, _, sentence, spans in sorted(
                grouped.values(), key=lambda value: value[1]
            )
        ]
        document = (
            text.rstrip()
            + "\n\n"
            + _semeval_block("json-attributes", attributes)
            + "\n"
            + _semeval_block("json-annotations", {"annotations": annotations})
        )
        (corpus / f"article{article}.md").write_text(document, encoding="utf-8")
