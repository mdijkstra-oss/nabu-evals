from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class GoldValidationError(ValueError):
    """A supplied gold root does not satisfy the qualitative-coding contract."""


_FENCE = re.compile(
    r"^```(?P<language>json-callout|json-annotations)\s*\n(?P<body>.*?)\n```\s*$",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class GoldRoot:
    path: Path
    name: str
    hash: str
    document_count: int
    token_estimate: int
    labels: int
    annotations: int
    negatives: int
    coding_density: float
    code_ids: tuple[str, ...]
    documents: tuple[str, ...]

    def manifest(self) -> dict[str, Any]:
        value = asdict(self)
        value["path"] = str(self.path)
        value["code_ids"] = list(self.code_ids)
        value["documents"] = list(self.documents)
        return value


def _blocks(markdown: str, language: str, source: Path) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for match in _FENCE.finditer(markdown):
        if match.group("language") != language:
            continue
        try:
            value = json.loads(match.group("body"))
        except json.JSONDecodeError as error:
            raise GoldValidationError(
                f"{source}: malformed {language}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise GoldValidationError(f"{source}: {language} must contain an object")
        parsed.append(value)
    return parsed


def _tree_hash(files: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(files):
        digest.update(str(file.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_gold_root(path: Path) -> GoldRoot:
    root = path.expanduser().resolve()
    codebook = root / "codebook.md"
    corpus = root / "corpus"
    if not codebook.is_file():
        raise GoldValidationError(f"{root}: missing codebook.md")
    if not corpus.is_dir():
        raise GoldValidationError(f"{root}: missing corpus directory")

    callouts = _blocks(codebook.read_text(encoding="utf-8"), "json-callout", codebook)
    code_ids: list[str] = []
    for index, callout in enumerate(callouts):
        code = callout.get("id")
        if not isinstance(code, str) or not code:
            raise GoldValidationError(
                f"{codebook}: callout {index} has no non-empty id"
            )
        code_ids.append(code)
    if not code_ids:
        raise GoldValidationError(f"{codebook}: no json-callout definitions")
    duplicates = sorted({code for code in code_ids if code_ids.count(code) > 1})
    if duplicates:
        raise GoldValidationError(
            f"{codebook}: duplicate callout IDs: {', '.join(duplicates)}"
        )

    documents = sorted(corpus.glob("*.md"))
    if not documents:
        raise GoldValidationError(f"{corpus}: no Markdown documents")
    annotation_count = 0
    negative_count = 0
    token_estimate = 0
    known = set(code_ids)
    for document in documents:
        markdown = document.read_text(encoding="utf-8")
        token_estimate += len(re.findall(r"\S+", markdown))
        annotation_blocks = _blocks(markdown, "json-annotations", document)
        if len(annotation_blocks) != 1:
            raise GoldValidationError(
                f"{document}: expected exactly one schema-valid json-annotations block"
            )
        annotations = annotation_blocks[0].get("annotations")
        if not isinstance(annotations, list):
            raise GoldValidationError(f"{document}: annotations must be a list")
        if not annotations:
            negative_count += 1
        for index, annotation in enumerate(annotations):
            if not isinstance(annotation, dict):
                raise GoldValidationError(
                    f"{document}: annotation {index} must be an object"
                )
            required = ("text", "reason", "code", "actor")
            invalid = [
                key for key in required if not isinstance(annotation.get(key), str)
            ]
            if invalid:
                raise GoldValidationError(
                    f"{document}: annotation {index} has invalid fields: {', '.join(invalid)}"
                )
            code = annotation["code"]
            if code not in known:
                raise GoldValidationError(f"{document}: unknown gold code ID {code!r}")
        annotation_count += len(annotations)
    if annotation_count == 0:
        raise GoldValidationError(
            f"{root}: at least one positive gold annotation is required"
        )

    return GoldRoot(
        path=root,
        name=root.name,
        hash=_tree_hash([codebook, *documents], root),
        document_count=len(documents),
        token_estimate=token_estimate,
        labels=len(code_ids),
        annotations=annotation_count,
        negatives=negative_count,
        coding_density=annotation_count / len(documents),
        code_ids=tuple(code_ids),
        documents=tuple(document.name for document in documents),
    )


def callouts_of(root: GoldRoot) -> list[dict[str, Any]]:
    codebook = root.path / "codebook.md"
    return _blocks(codebook.read_text(encoding="utf-8"), "json-callout", codebook)
