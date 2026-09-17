from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path

from nabu_evals.evaluation import run_evaluation
from nabu_evals.gold import load_gold_root
from nabu_evals.optimizer import OptimizerSettings


def _root(path: Path) -> Path:
    (path / "codes").mkdir(parents=True)
    (path / "corpus").mkdir()
    (path / "framework.md").write_text("Framework\n", encoding="utf-8")
    (path / "codes" / "code.md").write_text(
        "```json-callout\n"
        '{"id":"code","type":"note","title":"Code","content":"Find evidence.","color":"blue","collapsed":false}'
        "\n```\n",
        encoding="utf-8",
    )
    (path / "corpus" / "document.md").write_text(
        "Evidence.\n\n```json-annotations\n"
        '{"annotations":[{"text":"Evidence.","reason":"gold","code":"code","actor":"gold"}]}'
        "\n```\n",
        encoding="utf-8",
    )
    return path


def test_runs_the_fixed_baseline_without_reflection(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    prompts = tmp_path / "prompts"
    guidance = prompts / "config" / "deep-analysis-filter"
    guidance.mkdir(parents=True)
    (guidance / "coding-guidance.md").write_text("Baseline.\n", encoding="utf-8")
    root = load_gold_root(_root(tmp_path / "gold"))
    captured: dict[str, object] = {}

    class FakeDragoman(AbstractContextManager["FakeDragoman"]):
        port = 1234

        def __init__(self, _: object) -> None:
            pass

        def __exit__(self, *args: object) -> None:
            pass

    class FakeTarget:
        frontend_invocations = 1
        coding_requests = 2

        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def evaluate_batch(
            self, pairs: list[tuple[str, object]]
        ) -> list[tuple[float, dict[str, object]]]:
            captured["pairs"] = pairs
            return [(0.75, {"metrics": {"soft": {"f1": 0.75}}})]

    monkeypatch.setattr("nabu_evals.evaluation.DragomanRuntime", FakeDragoman)
    monkeypatch.setattr("nabu_evals.evaluation.QualCodingTarget", FakeTarget)
    settings = OptimizerSettings(
        frontend=tmp_path / "frontend",
        prompts=prompts,
        output=tmp_path / "output",
        chancery_bin="chancery",
        dragoman_bin="dragoman",
    )

    result = run_evaluation(settings, [root])

    assert captured["pairs"] == [("Baseline.", root)]
    assert result["kind"] == "fixed-coding-evaluation"
    assert result["evaluated_guidance"] == {
        "kind": "source",
        "hash": "1c40ee802b4414705d580f73fe9ea14a5945b964e699a713a893b6f628316d98",
    }
    assert result["reflection_calls"] == 0
    assert result["frontend_invocations"] == 1
    assert result["coding_requests"] == 2
    assert result["roots"] == [
        {"root": "gold", "score": 0.75, "metrics": {"soft": {"f1": 0.75}}}
    ]


def test_runs_supplied_guidance_without_editing_the_source_prompt(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    prompts = tmp_path / "prompts"
    guidance = prompts / "config" / "deep-analysis-filter"
    guidance.mkdir(parents=True)
    (guidance / "coding-guidance.md").write_text("Baseline.\n", encoding="utf-8")
    root = load_gold_root(_root(tmp_path / "gold"))
    captured: dict[str, object] = {}

    class FakeDragoman(AbstractContextManager["FakeDragoman"]):
        port = 1234

        def __init__(self, _: object) -> None:
            pass

        def __exit__(self, *args: object) -> None:
            pass

    class FakeTarget:
        frontend_invocations = 1
        coding_requests = 2

        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def evaluate_batch(
            self, pairs: list[tuple[str, object]]
        ) -> list[tuple[float, dict[str, object]]]:
            captured["pairs"] = pairs
            return [(0.75, {"metrics": {"soft": {"f1": 0.75}}})]

    monkeypatch.setattr("nabu_evals.evaluation.DragomanRuntime", FakeDragoman)
    monkeypatch.setattr("nabu_evals.evaluation.QualCodingTarget", FakeTarget)
    settings = OptimizerSettings(
        frontend=tmp_path / "frontend",
        prompts=prompts,
        output=tmp_path / "output",
        chancery_bin="chancery",
        dragoman_bin="dragoman",
    )

    result = run_evaluation(settings, [root], "Candidate.")

    assert captured["baseline"] == "Baseline."
    assert captured["pairs"] == [("Candidate.", root)]
    assert result["evaluated_guidance"]["kind"] == "supplied-file"
