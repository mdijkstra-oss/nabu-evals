from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any

from gepa.optimize_anything import (
    EngineConfig,
    GEPAConfig,
    ReflectionConfig,
    optimize_anything,
)

from nabu_evals.gold import GoldRoot
from nabu_evals.runtime import DragomanRuntime, RuntimeSettings
from nabu_evals.target import QualCodingTarget, candidate_hash

DEFAULT_REFLECTION_MODEL = "codex/gpt-5.6-sol"
DEFAULT_MODEL_TABLE = "models.codex.yaml"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8083"

REFLECTION_TEMPLATE = """You are improving one reusable qualitative-coding guidance component.

Current component:
```
<curr_param>
```

Deterministic evaluation diagnostics from the supplied optimization roots:
```
<side_info>
```

Propose complete replacement guidance that improves precision, recall, and span boundaries across
different corpora and codebooks. Preserve useful general behavior. State only general coding
strategies: never include corpus facts, document or callout identifiers, label-specific rules,
copied examples, or config/include syntax. The result must be usable with arbitrary definitions.

Return only the replacement component inside one triple-backtick block.
"""


@dataclass(frozen=True)
class OptimizerSettings:
    frontend: Path
    prompts: Path
    output: Path
    chancery_bin: str
    dragoman_bin: str
    reflection_model: str = DEFAULT_REFLECTION_MODEL
    npm_bin: str = "npm"
    model_table: str = DEFAULT_MODEL_TABLE
    bridge_url: str = DEFAULT_BRIDGE_URL
    max_candidate_proposals: int = 1
    per_root_timeout: int = 1_800
    total_timeout: int = 7_200
    max_frontend_invocations: int = 100
    max_coding_requests: int = 200


class PreserveProposalAcceptance:
    """Retain the one evaluated proposal even when it does not beat its parent."""

    def should_accept(self, proposal: object, state: object) -> bool:
        return True


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _version(command: str) -> str:
    try:
        result = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (result.stdout or result.stderr).strip().splitlines()[0]
    except OSError, subprocess.SubprocessError, IndexError:
        return "unknown"


def _revision(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except OSError, subprocess.SubprocessError:
        return "unknown"


class DragomanReflection:
    def __init__(
        self,
        *,
        gateway: str,
        model: str,
        output: Path,
        validate: Any,
    ) -> None:
        self.gateway = gateway.rstrip("/")
        self.model = model
        self.output = output
        self.validate = validate
        self.calls = 0

    @staticmethod
    def _prompt_text(prompt: object) -> str:
        if isinstance(prompt, str):
            return prompt
        return json.dumps(prompt, ensure_ascii=False, default=_json_default)

    @staticmethod
    def _component(response: str) -> str:
        matches = re.findall(r"```(?:markdown|md)?\s*\n(.*?)```", response, re.DOTALL)
        if len(matches) != 1:
            raise ValueError("response must contain exactly one fenced component")
        return matches[0].strip()

    def _call(self, prompt: str, suffix: str) -> str:
        self.calls += 1
        call_dir = self.output / "reflection" / f"call-{self.calls}-{suffix}"
        call_dir.mkdir(parents=True, exist_ok=True)
        (call_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        request = urllib.request.Request(
            f"{self.gateway}/responses",
            data=json.dumps(
                {
                    "model": self.model,
                    "input": prompt,
                    "reasoning": {"effort": "high"},
                    "store": False,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                payload = json.loads(response.read())
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            raise RuntimeError(
                f"Dragoman reflection request failed: {error}"
            ) from error
        (call_dir / "response.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        text = "".join(
            content["text"]
            for item in payload.get("output", [])
            if isinstance(item, dict)
            for content in item.get("content", [])
            if isinstance(content, dict)
            and content.get("type") == "output_text"
            and isinstance(content.get("text"), str)
        )
        if not text:
            raise RuntimeError("Dragoman reflection response has no output text")
        return text

    def __call__(self, prompt: object) -> str:
        prompt_text = self._prompt_text(prompt)
        response = self._call(prompt_text, "proposal")
        try:
            component = self._component(response)
            problems = self.validate(component)
        except ValueError as error:
            component = response.strip()
            problems = [str(error)]
        if problems:
            repair = (
                "Repair the proposed qualitative-coding guidance below.\n"
                "Return exactly one triple-backtick block and nothing else. Keep it generic.\n"
                "Do not include corpus facts, filenames, identifiers, label-specific rules, copied "
                "examples, or config syntax. Make it substantively different from the seed.\n\n"
                f"Validation failures: {json.dumps(problems)}\n\nProposal:\n{response}"
            )
            response = self._call(repair, "repair")
            component = self._component(response)
            repaired_problems = self.validate(component)
            if repaired_problems:
                raise ValueError(
                    "invalid repaired proposal: " + "; ".join(repaired_problems)
                )
        return f"```\n{component}\n```"


def run_optimizer(
    settings: OptimizerSettings, roots: Sequence[GoldRoot]
) -> dict[str, Any]:
    guidance_path = settings.prompts / "config/deep-analysis-filter/coding-guidance.md"
    baseline = guidance_path.read_text(encoding="utf-8").rstrip()
    source_prompt_hash = _tree_hash(settings.prompts / "config/deep-analysis-filter")
    runtime_settings = RuntimeSettings(
        prompts=settings.prompts,
        output=settings.output,
        chancery_bin=settings.chancery_bin,
        dragoman_bin=settings.dragoman_bin,
        model_table=settings.model_table,
        bridge_url=settings.bridge_url,
    )
    deadline = time.monotonic() + settings.total_timeout
    with DragomanRuntime(runtime_settings) as dragoman:
        target = QualCodingTarget(
            roots=roots,
            runtime=runtime_settings,
            frontend=settings.frontend,
            npm_bin=settings.npm_bin,
            dragoman_port=dragoman.port,
            per_root_timeout=settings.per_root_timeout,
            max_frontend_invocations=settings.max_frontend_invocations,
            max_coding_requests=settings.max_coding_requests,
            total_deadline=deadline,
            baseline=baseline,
        )
        reflection = DragomanReflection(
            gateway=f"http://127.0.0.1:{dragoman.port}",
            model=settings.reflection_model,
            output=settings.output,
            validate=target.validate_candidate,
        )

        def evaluate(
            pairs: list[tuple[str, GoldRoot]],
        ) -> list[tuple[float, dict[str, Any]]]:
            return target.evaluate_batch(pairs)

        config = GEPAConfig(
            engine=EngineConfig(
                run_dir=str(settings.output / "gepa"),
                seed=0,
                display_progress_bar=False,
                max_metric_calls=(settings.max_candidate_proposals + 1) * len(roots),
                max_candidate_proposals=settings.max_candidate_proposals,
                parallel=False,
                max_workers=1,
                cache_evaluation=True,
                cache_evaluation_storage="disk",
                use_cloudpickle=False,
                acceptance_criterion=PreserveProposalAcceptance(),
            ),
            reflection=ReflectionConfig(
                reflection_lm=reflection,
                reflection_minibatch_size=len(roots),
                module_selector="all",
                reflection_prompt_template=REFLECTION_TEMPLATE,
            ),
        )
        result = optimize_anything(
            seed_candidate=baseline,
            batch_evaluator=evaluate,
            dataset=list(roots),
            config=config,
        )

    if (
        _tree_hash(settings.prompts / "config/deep-analysis-filter")
        != source_prompt_hash
    ):
        raise RuntimeError("source prompt checkout changed during optimizer run")
    proposal_indices = [
        index
        for index, candidate in enumerate(result.candidates)
        if next(iter(candidate.values())).rstrip() != baseline
    ]
    if settings.max_candidate_proposals > 0 and not proposal_indices:
        raise RuntimeError("GEPA did not retain a distinct proposal")
    summary = {
        "kind": "optimization-set-proposal",
        "holdout_used": False,
        "source_prompt_hash_before": source_prompt_hash,
        "source_prompt_hash_after": source_prompt_hash,
        "frontend_invocations": target.frontend_invocations,
        "coding_requests": target.coding_requests,
        "reflection_calls": reflection.calls,
        "candidates": [
            {
                "index": index,
                "hash": candidate_hash(next(iter(candidate.values()))),
                "score": result.val_aggregate_scores[index],
                "parent": result.parents[index],
                "is_best": index == result.best_idx,
                "is_seed": index == 0,
            }
            for index, candidate in enumerate(result.candidates)
        ],
        "best_index": result.best_idx,
        "proposal_indices": proposal_indices,
    }
    for index, candidate in enumerate(result.candidates):
        text = next(iter(candidate.values())).rstrip()
        digest = candidate_hash(text)
        directory = next(
            (
                path.parent
                for path in (settings.output / "candidates").glob("*/process.json")
                if json.loads(path.read_text(encoding="utf-8")).get("candidate_hash")
                == digest
            ),
            None,
        )
        if directory is None:
            continue
        _write_json(
            directory / "candidate.json",
            {
                "index": index,
                "hash": digest,
                "score": result.val_aggregate_scores[index],
                "parent": result.parents[index],
                "is_best": index == result.best_idx,
                "scope": "supplied optimization roots only",
            },
        )
        if index > 0:
            (directory / "diff.patch").write_text(
                "".join(
                    unified_diff(
                        baseline.splitlines(keepends=True),
                        (text + "\n").splitlines(keepends=True),
                        fromfile="baseline/coding-guidance.md",
                        tofile=f"candidate-{index}/coding-guidance.md",
                    )
                ),
                encoding="utf-8",
            )
    _write_json(settings.output / "gepa-result.json", result.to_dict())
    _write_json(settings.output / "scores.json", summary)
    _write_json(
        settings.output / "best.json",
        {
            "candidate_index": result.best_idx,
            "candidate_hash": summary["candidates"][result.best_idx]["hash"],
            "scope": "supplied optimization roots only",
        },
    )
    _write_json(
        settings.output / "versions.json",
        {
            "frontend_revision": _revision(settings.frontend),
            "prompts_revision": _revision(settings.prompts),
            "chancery": _version(settings.chancery_bin),
            "dragoman": _version(settings.dragoman_bin),
            "reflection_transport": "dragoman",
            "reflection_model": settings.reflection_model,
            "gepa": "0.1.4",
            "settings": asdict(settings),
        },
    )
    return summary
