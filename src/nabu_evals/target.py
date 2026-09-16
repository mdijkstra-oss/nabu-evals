from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from nabu_evals.gold import GoldRoot, callouts_of
from nabu_evals.runtime import CandidateRuntime, RuntimeFailure, RuntimeSettings


@dataclass(frozen=True)
class Evaluation:
    score: float
    feedback: dict[str, Any]
    result_path: Path


class EvaluationTarget(Protocol):
    """The bounded system that turns a prompt component and gold root into a score."""

    def validate_candidate(self, candidate: str) -> list[str]: ...

    def evaluate_batch(
        self, pairs: Sequence[tuple[str, GoldRoot]]
    ) -> list[tuple[float, dict[str, Any]]]: ...


def candidate_hash(candidate: str) -> str:
    return hashlib.sha256(candidate.rstrip().encode()).hexdigest()


def _trim(value: object, limit: int = 320) -> str:
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class QualCodingTarget:
    def __init__(
        self,
        *,
        roots: Sequence[GoldRoot],
        runtime: RuntimeSettings,
        frontend: Path,
        npm_bin: str,
        dragoman_port: int,
        per_root_timeout: int,
        max_frontend_invocations: int,
        max_coding_requests: int,
        total_deadline: float,
        baseline: str,
    ) -> None:
        self.roots = list(roots)
        self.runtime = runtime
        self.frontend = frontend
        self.npm_bin = npm_bin
        self.dragoman_port = dragoman_port
        self.per_root_timeout = per_root_timeout
        self.max_frontend_invocations = max_frontend_invocations
        self.max_coding_requests = max_coding_requests
        self.total_deadline = total_deadline
        self.baseline = baseline.rstrip()
        self.frontend_invocations = 0
        self.coding_requests = 0
        self._cache: dict[tuple[str, str], Evaluation] = {}
        self._names: dict[str, str] = {}
        self._forbidden = self._forbidden_material()

    def _forbidden_material(self) -> list[tuple[str, str]]:
        forbidden: list[tuple[str, str]] = []
        for root in self.roots:
            forbidden.extend((code.lower(), "callout ID") for code in root.code_ids)
            forbidden.extend(
                (name.lower(), "corpus filename") for name in root.documents
            )
            sources = [root.path / "codebook.md", *(root.path / "corpus").glob("*.md")]
            for source in sources:
                words = source.read_text(encoding="utf-8").lower().split()
                for start in range(max(0, len(words) - 11)):
                    phrase = " ".join(words[start : start + 12])
                    forbidden.append(
                        (
                            phrase,
                            "codebook/corpus passage"
                            if source.name == "codebook.md"
                            else "gold passage",
                        )
                    )
        return forbidden

    def validate_candidate(self, candidate: str) -> list[str]:
        stripped = candidate.strip()
        problems: list[str] = []
        if not stripped:
            problems.append("proposal is empty")
        if stripped == self.baseline:
            problems.append("proposal is identical to the seed")
        if len(stripped) > 8_000:
            problems.append("proposal exceeds 8,000 characters")
        lowered = " ".join(stripped.lower().split())
        if (
            "```" in stripped
            or "json-callout" in lowered
            or "[coding-guidance.md]" in lowered
        ):
            problems.append("proposal contains wrapper/config syntax")
        seen_kinds: set[str] = set()
        for value, kind in self._forbidden:
            if value and value in lowered and kind not in seen_kinds:
                problems.append(f"proposal contains a {kind}")
                seen_kinds.add(kind)
        return problems

    def _candidate_name(self, digest: str) -> str:
        if digest not in self._names:
            self._names[digest] = (
                "baseline" if not self._names else f"proposal-{len(self._names)}"
            )
        return self._names[digest]

    def _check_limits(self) -> None:
        if time.monotonic() > self.total_deadline:
            raise RuntimeFailure("optimizer exceeded total wall-time limit")
        if self.frontend_invocations >= self.max_frontend_invocations:
            raise RuntimeFailure("optimizer exceeded frontend invocation limit")

    def _run_root(
        self,
        candidate: str,
        digest: str,
        name: str,
        runtime: CandidateRuntime,
        root: GoldRoot,
        root_index: int,
    ) -> Evaluation:
        root_dir = (
            self.runtime.output
            / "candidates"
            / name
            / "roots"
            / f"root-{root_index + 1}"
        )
        last_error = "frontend failed"
        root_requests = 0
        for attempt in (1, 2):
            self._check_limits()
            self.frontend_invocations += 1
            attempt_dir = root_dir / f"attempt-{attempt}"
            command = [
                self.npm_bin,
                "run",
                "eval:coding:batch",
                "--",
                "--gold-dir",
                str(root.path),
                "--output",
                str(attempt_dir),
                "--gateway",
                runtime.gateway,
                "--passthrough",
                "retrieval,semantic-filter",
                "--coders",
                "voter-one",
                "--adjudicate",
                "false",
                "--prompt-root",
                str(runtime.config),
                "--prompt-hash",
                digest,
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.frontend,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.per_root_timeout,
                )
            except subprocess.TimeoutExpired as error:
                last_error = (
                    f"frontend timed out after {self.per_root_timeout}s: {error}"
                )
                continue
            root_dir.mkdir(parents=True, exist_ok=True)
            (root_dir / f"attempt-{attempt}.process.log").write_text(
                completed.stdout + completed.stderr, encoding="utf-8"
            )
            if completed.returncode != 0:
                last_error = f"frontend exited {completed.returncode}"
                continue
            try:
                results = json.loads(
                    (attempt_dir / "results.json").read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                last_error = f"missing or malformed frontend results: {error}"
                continue
            returned = [
                document.get("name") for document in results.get("documents", [])
            ]
            if sorted(returned) != sorted(root.documents) or len(returned) != len(
                set(returned)
            ):
                last_error = (
                    "frontend returned an incomplete or unexpected document set"
                )
                continue
            requests = len(results.get("requests", []))
            root_requests += requests
            self.coding_requests += requests
            if root_requests > self.max_coding_requests:
                raise RuntimeFailure(
                    "root exceeded coding-request limit "
                    f"({root_requests}>{self.max_coding_requests})"
                )
            statuses = {document.get("status") for document in results["documents"]}
            if "failed" in statuses:
                last_error = "frontend reported a provider or pipeline failure"
                continue
            endpoints = results.get("endpoints", [])
            if any(
                endpoint != "/deep-analysis-filter.voter-one" for endpoint in endpoints
            ):
                raise RuntimeFailure(f"unexpected endpoint(s): {endpoints}")
            score = float(results.get("soft", {}).get("f1", 0))
            feedback = self._feedback(root, root_index, results)
            (root_dir / "feedback.json").write_text(
                json.dumps(feedback, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return Evaluation(score=score, feedback=feedback, result_path=attempt_dir)
        raise RuntimeFailure(
            f"root-{root_index + 1} remained invalid after one retry: {last_error}"
        )

    def _feedback(
        self, root: GoldRoot, root_index: int, results: dict[str, Any]
    ) -> dict[str, Any]:
        aliases = {
            code: f"label-{index + 1}" for index, code in enumerate(root.code_ids)
        }
        definitions = {
            aliases[str(callout["id"])]: {
                "title": f"Definition {index + 1}",
                "definition": _trim(callout.get("content", ""), 420),
            }
            for index, callout in enumerate(callouts_of(root))
        }
        examples: list[dict[str, Any]] = []
        for document_index, document in enumerate(results.get("documents", [])):
            comparison = document.get("comparison") or {}
            for kind, key in (
                ("false-positive", "falsePositives"),
                ("false-negative", "falseNegatives"),
            ):
                for finding in comparison.get(key, [])[:2]:
                    examples.append(
                        {
                            "kind": kind,
                            "document": f"document-{document_index + 1}",
                            "label": aliases.get(finding.get("code"), "unknown-label"),
                            "text": _trim(finding.get("text", "")),
                            "range": finding.get("range"),
                        }
                    )
            for match in comparison.get("matches", [])[:2]:
                iou = float(match.get("iou", 0))
                if iou < 1:
                    predicted = match.get("prediction", {})
                    gold = match.get("gold", {})
                    predicted_width = predicted.get("range", {}).get(
                        "end", 0
                    ) - predicted.get("range", {}).get("start", 0)
                    gold_width = gold.get("range", {}).get("end", 0) - gold.get(
                        "range", {}
                    ).get("start", 0)
                    examples.append(
                        {
                            "kind": "too-wide"
                            if predicted_width > gold_width
                            else "too-narrow",
                            "document": f"document-{document_index + 1}",
                            "label": aliases.get(
                                predicted.get("code"), "unknown-label"
                            ),
                            "iou": iou,
                            "predicted_text": _trim(predicted.get("text", "")),
                            "gold_text": _trim(gold.get("text", "")),
                        }
                    )
            if len(examples) >= 8:
                break
        per_code = [
            {**score, "code": aliases.get(score.get("code"), "unknown-label")}
            for score in results.get("perCode", [])
        ]
        return {
            "root": f"root-{root_index + 1}",
            "optimization_set_only": True,
            "metrics": {
                "soft": results.get("soft"),
                "relaxed": results.get("relaxed"),
                "exact": results.get("exact"),
                "per_label": per_code,
            },
            "quality": {
                "complete": results.get("complete"),
                "outcomes": results.get("outcomes"),
                "diagnostics": [
                    _trim(item) for item in results.get("diagnostics", [])[:4]
                ],
            },
            "definitions": definitions,
            "representative_errors": examples[:8],
        }

    def evaluate_batch(
        self, pairs: Sequence[tuple[str, GoldRoot]]
    ) -> list[tuple[float, dict[str, Any]]]:
        output: list[tuple[float, dict[str, Any]] | None] = [None] * len(pairs)
        grouped: OrderedDict[str, list[tuple[int, str, GoldRoot]]] = OrderedDict()
        for index, (candidate, root) in enumerate(pairs):
            digest = candidate_hash(candidate)
            grouped.setdefault(digest, []).append((index, candidate, root))
        for digest, group in grouped.items():
            uncached = [
                row for row in group if (digest, row[2].hash) not in self._cache
            ]
            if uncached:
                candidate = uncached[0][1]
                problems = (
                    []
                    if candidate.rstrip() == self.baseline
                    else self.validate_candidate(candidate)
                )
                if problems:
                    raise ValueError("invalid candidate: " + "; ".join(problems))
                name = self._candidate_name(digest)
                with CandidateRuntime(
                    self.runtime, candidate, digest, name, self.dragoman_port
                ) as candidate_runtime:
                    (candidate_runtime.directory / "rendered-prompt.md").write_text(
                        render_prompt(candidate_runtime.config), encoding="utf-8"
                    )
                    for _, _, root in uncached:
                        root_index = self.roots.index(root)
                        evaluation = self._run_root(
                            candidate, digest, name, candidate_runtime, root, root_index
                        )
                        self._cache[(digest, root.hash)] = evaluation
            for index, _, root in group:
                evaluation = self._cache[(digest, root.hash)]
                output[index] = (evaluation.score, evaluation.feedback)
        return [item for item in output if item is not None]


def render_prompt(config: Path) -> str:
    agent = config / "deep-analysis-filter" / "index.md"
    markdown = agent.read_text(encoding="utf-8").replace("\r\n", "\n")
    if markdown.startswith("---\n"):
        _, _, markdown = markdown.partition("\n---\n")
    rendered: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith(".md]"):
            relative = stripped[1:-1]
            local = agent.parent / relative
            shared = config / "shared" / relative
            include = local if local.is_file() else shared
            rendered.append(include.read_text(encoding="utf-8").rstrip("\n"))
        else:
            rendered.append(line)
    return "\n".join(rendered).strip() + "\n"
