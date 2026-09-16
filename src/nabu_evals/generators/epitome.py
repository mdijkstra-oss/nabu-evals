from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_EXAMPLE_CONTEXT = (
    'All examples respond to the seeker post: "I am about to have an anxiety attack."'
)

_EMOTIONAL_REACTIONS = (
    "Expressing emotions such as warmth, compassion, and concern, experienced by the "
    "peer supporter after reading the seeker’s post. Expressing these emotions plays an "
    "important role in establishing empathic rapport and support."
)
_INTERPRETATIONS = (
    "Communicating an understanding of feelings and experiences inferred from the seeker’s "
    "post. Such a cognitive understanding in responses is helpful in increasing awareness "
    "of hidden feelings and experiences, and essential for developing alliance between the "
    "seeker and peer supporter."
)
_EXPLORATIONS = (
    "Improving understanding of the seeker by exploring the feelings and experiences not "
    "stated in the post. Showing an active interest in what the seeker is experiencing and "
    "feeling and probing gently is another important aspect of empathy."
)


@dataclass(frozen=True)
class _Code:
    title: str
    color: str
    definition: str


_CODES = {
    "emotional-reactions-weak": _Code(
        title="Emotional reactions (weak)",
        color="tomato",
        definition=(
            f"{_EMOTIONAL_REACTIONS}\n\nWeak communication alludes to these emotions "
            f'without the emotions being explicitly labeled.\n\nEx.: "Everything will be '
            f'fine." {_EXAMPLE_CONTEXT}'
        ),
    ),
    "emotional-reactions-strong": _Code(
        title="Emotional reactions (strong)",
        color="red",
        definition=(
            f"{_EMOTIONAL_REACTIONS}\n\nStrong communication specifies the experienced "
            f'emotions.\n\nEx.: "I feel really sad for you." {_EXAMPLE_CONTEXT}'
        ),
    ),
    "interpretations-weak": _Code(
        title="Interpretations (weak)",
        color="sky",
        definition=(
            f"{_INTERPRETATIONS}\n\nWeak communication contains a mention of the "
            f'understanding.\n\nEx.: "I understand how you feel." {_EXAMPLE_CONTEXT}'
        ),
    ),
    "interpretations-strong": _Code(
        title="Interpretations (strong)",
        color="blue",
        definition=(
            f"{_INTERPRETATIONS}\n\nStrong communication specifies the inferred feeling "
            f"or experience, or communicates understanding through descriptions of similar "
            f'experiences.\n\nEx.: "This must be terrifying"; "I also have anxiety '
            f'attacks at times which makes me really terrified." {_EXAMPLE_CONTEXT}'
        ),
    ),
    "explorations-weak": _Code(
        title="Explorations (weak)",
        color="mint",
        definition=(
            f'{_EXPLORATIONS}\n\nA weak exploration is generic.\n\nEx.: "What happened?" '
            f"{_EXAMPLE_CONTEXT}"
        ),
    ),
    "explorations-strong": _Code(
        title="Explorations (strong)",
        color="green",
        definition=(
            f"{_EXPLORATIONS}\n\nA strong exploration is specific and labels the seeker’s "
            f"experiences and feelings which the peer supporter wants to explore.\n\nEx.: "
            f'"Are you feeling alone right now?" {_EXAMPLE_CONTEXT}'
        ),
    ),
}


@dataclass(frozen=True)
class _Mechanism:
    file: str
    label: str
    key: str


_MECHANISMS = (
    _Mechanism(
        file="emotional-reactions-reddit.csv",
        label="Emotional reactions",
        key="emotional-reactions",
    ),
    _Mechanism(
        file="interpretations-reddit.csv",
        label="Interpretations",
        key="interpretations",
    ),
    _Mechanism(
        file="explorations-reddit.csv",
        label="Explorations",
        key="explorations",
    ),
)


@dataclass
class _GoldLabel:
    level: int
    rationales: list[str]


@dataclass
class _Pair:
    seeker: str
    response: str
    gold: dict[str, _GoldLabel] = field(default_factory=dict)


def _callout_id(label: str) -> str:
    digest = hashlib.sha256(f"epitome:{label}".encode()).hexdigest()
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    value = int(digest[2:16], 16)
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = alphabet[remainder] + encoded
    return f"callout-{int(digest[:2], 16) % 10}{encoded.rjust(7, '0')[:7]}"


def _format_block(language: str, value: object) -> str:
    return f"```{language}\n{json.dumps(value, indent=2, ensure_ascii=False)}\n```\n"


def _rationale_description(rationale: str) -> str:
    return json.dumps(re.sub(r"\s+", " ", rationale)[:120], ensure_ascii=False)


def _normalized(text: str) -> tuple[str, list[int]]:
    normalized = ""
    positions: list[int] = []
    for index, character in enumerate(text):
        if character in "’‘":
            character = "'"
        elif character in "“”":
            character = '"'
        elif character.isspace():
            character = " "
        else:
            character = character.lower()
        if character == " " and (not normalized or normalized.endswith(" ")):
            continue
        normalized += character
        positions.append(index)
    return normalized, positions


def _rationale_span(
    document: str, response_start: int, rationale: str
) -> tuple[int, int] | None:
    exact = document.find(rationale, response_start)
    if exact >= 0:
        return exact, exact + len(rationale)
    normalized_region, positions = _normalized(document[response_start:])
    normalized_rationale, _ = _normalized(rationale)
    normalized_rationale = normalized_rationale.strip()
    if not normalized_rationale:
        return None
    index = normalized_region.find(normalized_rationale)
    if index < 0:
        return None
    return (
        response_start + positions[index],
        response_start + positions[index + len(normalized_rationale) - 1] + 1,
    )


def _sentence_rows(text: str) -> list[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"(?:(?<=[.!?])(?:\s+|$)|(?<=:)\n{2,})", text):
        end = match.start()
        while start < end and text[start].isspace():
            start += 1
        if start < end:
            rows.append((start, end))
        start = match.end()
    while start < len(text) and text[start].isspace():
        start += 1
    if start < len(text):
        rows.append((start, len(text)))
    return rows


def _overlapping_sentence_span(
    rows: list[tuple[int, int]], start: int, end: int
) -> tuple[int, int] | None:
    overlaps = [
        (row_start, row_end)
        for row_start, row_end in rows
        if row_end > start and row_start < end
    ]
    if not overlaps:
        return None
    return overlaps[0][0], overlaps[-1][1]


def _read_pairs(data_dir: Path) -> tuple[dict[str, _Pair], int]:
    pairs: dict[str, _Pair] = {}
    conflicts = 0
    for mechanism in _MECHANISMS:
        with (data_dir / mechanism.file).open(encoding="utf-8", newline="") as stream:
            records = csv.DictReader(stream)
            for row in records:
                identifier = f"{row['sp_id']}-{row['rp_id']}"
                pair = pairs.setdefault(
                    identifier,
                    _Pair(seeker=row["seeker_post"], response=row["response_post"]),
                )
                level = int(row["level"])
                if level not in (0, 1, 2):
                    raise ValueError(
                        f"bad level {row['level']} in {mechanism.file} for {identifier}"
                    )
                if level == 0:
                    continue
                rationales = [
                    rationale
                    for rationale in row["rationales"].split("|")
                    if rationale.strip()
                ]
                current = pair.gold.get(mechanism.key)
                if current is None:
                    pair.gold[mechanism.key] = _GoldLabel(level, rationales)
                elif current.level == level:
                    current.rationales.extend(rationales)
                else:
                    conflicts += 1
                    if level > current.level:
                        pair.gold[mechanism.key] = _GoldLabel(level, rationales)
    return pairs, conflicts


def _write_sources(output_dir: Path) -> None:
    (output_dir / "corpus").mkdir(parents=True, exist_ok=True)
    codes = output_dir / "codes"
    codes.mkdir(parents=True, exist_ok=True)
    framework = (
        "# EPITOME empathy mechanisms\n\n"
        "Codebook of the EPITOME gold labels (Reddit subset). Definitions verbatim from "
        "Sharma et al. (2020), Section 2 — the framework the annotators were trained on. "
        "Each mechanism is coded at the level communicated: weak or strong. No communication "
        "of a mechanism carries no code; the paper counts responses that only give advice, "
        "only provide factual information, or are offensive as no communication of empathy.\n"
    )
    (output_dir / "framework.md").write_text(framework, encoding="utf-8")
    for label, code in _CODES.items():
        callout = {
            "id": _callout_id(label),
            "type": "codebook-code",
            "title": code.title,
            "color": code.color,
            "collapsed": False,
            "content": code.definition,
        }
        (codes / f"{callout['id']}.md").write_text(
            _format_block("json-callout", callout), encoding="utf-8"
        )


def generate_epitome(data_dir: Path, output_dir: Path) -> dict[str, int]:
    """Generate a normal coding project from EPITOME's three Reddit CSV files."""
    data_dir = data_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    _write_sources(output_dir)
    pairs, conflicts = _read_pairs(data_dir)
    unanchored = 0
    without_rationale = 0
    annotation_count = 0
    total_rationales = 0
    mechanism_by_key = {mechanism.key: mechanism for mechanism in _MECHANISMS}

    for identifier, pair in pairs.items():
        prefix = f"Seeker post:\n\n{pair.seeker.strip()}\n\nResponse:\n\n"
        document = prefix + pair.response.strip()
        rows = _sentence_rows(document)
        annotations: dict[tuple[str, int, int], dict[str, Any]] = {}
        for mechanism_key, gold in pair.gold.items():
            level = "weak" if gold.level == 1 else "strong"
            code_key = f"{mechanism_key}-{level}"
            mechanism = mechanism_by_key[mechanism_key]
            label = f"{mechanism.label}, {level}"
            if not gold.rationales:
                without_rationale += 1
                continue
            for rationale in gold.rationales:
                total_rationales += 1
                span = _rationale_span(document, len(prefix), rationale)
                if span is None:
                    unanchored += 1
                    continue
                sentence_span = _overlapping_sentence_span(rows, *span)
                if sentence_span is None:
                    unanchored += 1
                    continue
                key = (code_key, *sentence_span)
                annotation = annotations.get(key)
                if annotation is None:
                    annotations[key] = {
                        "text": document[sentence_span[0] : sentence_span[1]],
                        "reason": f"Gold ({label}) — rationale: {_rationale_description(rationale)}",
                        "code": _callout_id(code_key),
                        "actor": "user",
                    }
                else:
                    annotation["reason"] += f", {_rationale_description(rationale)}"
        ordered = [
            annotations[key]
            for key in sorted(annotations, key=lambda key: (key[1], key[2], key[0]))
        ]
        annotation_count += len(ordered)
        attributes = {
            "type": "peer-support-exchange",
            "source": "EPITOME (Sharma et al. 2020), Reddit subset",
            "subject": pair.seeker[:77] + "..."
            if len(pair.seeker) > 80
            else pair.seeker,
        }
        corpus = (
            document.rstrip()
            + "\n\n"
            + _format_block("json-attributes", attributes)
            + "\n"
            + _format_block("json-annotations", {"annotations": ordered})
        )
        (output_dir / "corpus" / f"{identifier}.md").write_text(
            corpus, encoding="utf-8"
        )
    if total_rationales and unanchored / total_rationales > 0.05:
        raise ValueError(f"{unanchored}/{total_rationales} rationales failed to anchor")
    return {
        "codes": len(_CODES),
        "exchanges": len(pairs),
        "annotations": annotation_count,
        "unanchorable_rationales": unanchored,
        "labels_without_rationale": without_rationale,
        "level_conflicts": conflicts,
    }
