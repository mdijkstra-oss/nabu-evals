"""Generate normal Nabu coding sources from the AnnoMI-full.csv dataset."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class _Code:
    title: str
    color: str
    definition: str


_QUESTION = (
    "Therapists use asking to develop an understanding of the client and their "
    "problems; any question is either open or closed, in accordance with "
    "mainstream MI coding conventions."
)
_INPUT = (
    "The primary manner of communicating knowledge to the client is informing. "
    "Input covers a wide range of conveyed knowledge, in four subtypes: "
    "providing information, giving advice, presenting options, and setting goals "
    "(negotiation). When an utterance contains more than one type of input, the "
    "main type is labeled."
)
_REFLECTION = (
    "Reflection is an essential means of listening: the therapist shows that they "
    "are listening to and understanding the client, which is effective in helping "
    "people to change."
)

_CODES = {
    "question-open": _Code(
        "Open question",
        "blue",
        f'{_QUESTION}\n\nAn open question allows a wide range of possible answers and may seek information, invite the client’s perspective, or encourage self-exploration.\n\nEx.: "So what is a typical week for you as far as your alcohol use is concerned?" (seek information); "Okay. So how do you feel about being here today?" (invite the client’s perspective); "So, when you think about what you like and don’t like about your drinking, where do you wanna go from here?" (encourage self-exploration).',
    ),
    "question-closed": _Code(
        "Closed question",
        "indigo",
        f'{_QUESTION}\n\nA closed question implies a short answer such as Yes/No, a specific fact, a number, etc.\n\nEx.: "Do you have children in your house?" (Yes/No); "How much does it actually cost you a week?" (number); "Okay. What kind of alcohol do you drink at parties?" (specific fact).',
    ),
    "input-information": _Code(
        "Input — information",
        "amber",
        f'{_INPUT}\n\nThis code: providing information.\n\nEx.: "You’re not alone in feeling that way. Binge drinking can feel normal to some people."; "So that’s a hormone that allows you to utilise sugar in your body."',
    ),
    "input-advice": _Code(
        "Input — advice",
        "orange",
        f'{_INPUT}\n\nThis code: giving advice.\n\nEx.: "I want you to be healthy. And I don’t want to see you coming back in here for something else. So I’m really gonna recommend that you try to cut down to that amount."; "That’s why I recommend that all my adolescent patients not drink at all."',
    ),
    "input-options": _Code(
        "Input — options",
        "gold",
        f'{_INPUT}\n\nThis code: presenting options.\n\nEx.: "So, what have you looked into about, um, you know, advocacy in that area or expungement or anything like that?"; "Okay. So, exploring some yoga classes. Is doing yoga in your living room appealing to you at all?"',
    ),
    "input-negotiation": _Code(
        "Input — negotiation/goal setting",
        "bronze",
        f'{_INPUT}\n\nThis code: setting goals (negotiation).\n\nEx.: "So for you being in your class, when that bell rings, then you know, this is the goal."; "Do you think you could go two months without drinking?"',
    ),
    "reflection-simple": _Code(
        "Simple reflection",
        "green",
        f'{_REFLECTION}\n\nA simple reflection shows an understanding of the client’s words but contains little additional meaning — for example, by repeating the client’s statement. It identifies the client’s emotion or situation without going beyond the overt content of the client’s statement.\n\nEx.: to a client stressed as a single mom with a full-time job who started smoking again: "Things are very stressful for you right now."',
    ),
    "reflection-complex": _Code(
        "Complex reflection",
        "jade",
        f'{_REFLECTION}\n\nA complex reflection conveys a deeper level of understanding of the client’s point of view and adds substantial meaning to the client’s statement, using techniques such as metaphors and exaggeration — "continuing the paragraph" by interpreting the client’s words and anticipating what they might reasonably say next.\n\nEx.: to the same client: "You have a lot of things going on and smoking’s kind of a way to relax and de-stress."',
    ),
    "client-change": _Code(
        "Change talk",
        "grass",
        'Clients usually feel ambivalent about adopting positive behaviour change; the desirable outcome of MI is for the client to pick up pro-change arguments and talk themselves into changing. Change talk favours change.\n\nEx.: "Yeah, I just want to do what’s right."; "Well, that was fine until I came here, um, but now that I know about the health risk, um, I have something I gotta think about."',
    ),
    "client-sustain": _Code(
        "Sustain talk",
        "ruby",
        'Sustain talk conveys resistance to behaviour change and favours the status quo.\n\nEx.: "Um, I mean, the 10 drinks seems like not a lot for me and my tolerance."; "Yeah, whatever. I know you got to do your job, but I don’t care."',
    ),
}

_BEHAVIOURS = (
    ("question_exists", "question_subtype", "question", "question"),
    ("reflection_exists", "reflection_subtype", "reflection", "reflection"),
    (
        "therapist_input_exists",
        "therapist_input_subtype",
        "input",
        "input",
    ),
)


@dataclass
class _Utterance:
    transcript: str
    order: int
    interlocutor: str
    text: str
    quality: str
    topic: str
    rows: list[dict[str, str]] = field(default_factory=list)


def _callout_id(label: str) -> str:
    digest = hashlib.sha256(f"annomi:{label}".encode()).hexdigest()
    digit = str(int(digest[:2], 16) % 10)
    value = int(digest[2:16], 16)
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = alphabet[remainder] + encoded
    return f"callout-{digit}{(encoded or '0').rjust(7, '0')[:7]}"


def _format_block(language: str, value: object) -> str:
    return f"```{language}\n{json.dumps(value, indent=2)}\n```\n"


def _plurality(votes: Iterable[str]) -> str | None:
    counts: dict[str, int] = {}
    for vote in votes:
        counts[vote] = counts.get(vote, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def _gold_labels(utterance: _Utterance) -> tuple[list[tuple[str, str, int, int]], int]:
    total = len(utterance.rows)
    labels: list[tuple[str, str, int, int]] = []
    ties = 0
    if utterance.interlocutor == "therapist":
        for exists, subtype_column, prefix, label in _BEHAVIOURS:
            present = [row for row in utterance.rows if row[exists] == "True"]
            if len(present) * 2 <= total:
                continue
            subtype = _plurality(row[subtype_column] for row in present)
            if subtype is None:
                ties += 1
                continue
            code = f"{prefix}-{subtype}"
            if code not in _CODES:
                raise ValueError(f"unknown gold label {code}")
            labels.append((code, f"{subtype} {label}", len(present), total))
    else:
        talk = _plurality(row["client_talk_type"] for row in utterance.rows)
        if talk is None:
            ties += 1
        elif talk in {"change", "sustain"}:
            votes = sum(row["client_talk_type"] == talk for row in utterance.rows)
            labels.append((f"client-{talk}", f"{talk} talk", votes, total))
        elif talk != "neutral":
            raise ValueError(f"unknown client talk type {talk}")
    return labels, ties


def _utterances(records: Iterable[dict[str, str]]) -> dict[str, dict[int, _Utterance]]:
    transcripts: dict[str, dict[int, _Utterance]] = defaultdict(dict)
    for row in records:
        transcript = row["transcript_id"]
        order = int(row["utterance_id"])
        utterance = transcripts[transcript].get(order)
        if utterance is None:
            utterance = _Utterance(
                transcript=transcript,
                order=order,
                interlocutor=row["interlocutor"],
                text=row["utterance_text"],
                quality=row["mi_quality"],
                topic=row["topic"],
            )
            transcripts[transcript][order] = utterance
        utterance.rows.append(row)
    return transcripts


def generate_annomi(data_dir: Path, output_dir: Path) -> None:
    """Generate framework, codes, corpus, and gold annotations from AnnoMI-full.csv."""
    data_dir = data_dir.expanduser()
    output_dir = output_dir.expanduser()
    with (data_dir / "AnnoMI-full.csv").open(encoding="utf-8", newline="") as source:
        records = list(csv.DictReader(source))

    corpus = output_dir / "corpus"
    codes = output_dir / "codes"
    corpus.mkdir(parents=True, exist_ok=True)
    codes.mkdir(parents=True, exist_ok=True)
    framework = (
        "# AnnoMI motivational interviewing codes\n\n"
        "Codebook of the AnnoMI gold labels. Definitions verbatim from Wu et al. "
        "(2023), Section 4 — the scheme the expert annotators worked from — with "
        "the paper’s examples (Tables 5–8). Therapist utterances containing no "
        "question, input, or reflection (“other”) and client talk with no preference "
        "for or against change (“neutral”) carry no code.\n"
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

    transcripts = _utterances(records)
    annotations_total = 0
    ties_total = 0
    for transcript, utterance_map in transcripts.items():
        utterances = sorted(
            utterance_map.values(), key=lambda utterance: utterance.order
        )
        paragraphs = [
            f"{'Therapist' if utterance.interlocutor == 'therapist' else 'Client'}: "
            f"{utterance.text.strip()}"
            for utterance in utterances
        ]
        annotations: list[dict[str, str]] = []
        for paragraph, utterance in zip(paragraphs, utterances, strict=True):
            labels, ties = _gold_labels(utterance)
            ties_total += ties
            for code, label, votes, total in labels:
                annotations.append(
                    {
                        "text": paragraph,
                        "reason": "Gold ("
                        + label
                        + ")"
                        + (f" — {votes}/{total} annotators" if total > 1 else ""),
                        "code": _callout_id(code),
                        "actor": "user",
                    }
                )
        annotations_total += len(annotations)
        first = utterances[0]
        attributes = {
            "type": "counselling-transcript",
            "source": "AnnoMI (Wu et al. 2023)",
            "subject": f"{first.topic} — {first.quality}-quality MI"[:80],
        }
        document = (
            "\n\n".join(paragraphs).rstrip()
            + "\n\n"
            + _format_block("json-attributes", attributes)
            + "\n"
            + _format_block("json-annotations", {"annotations": annotations})
        )
        (corpus / f"transcript-{transcript.zfill(3)}.md").write_text(
            document, encoding="utf-8"
        )
    print(
        f"codebook: {len(_CODES)} codes; corpus: {len(transcripts)} "
        f"transcripts; annotations: {annotations_total} "
        f"({ties_total} unresolved annotator ties dropped)"
    )
