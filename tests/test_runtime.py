from __future__ import annotations

import pytest

from nabu_evals.runtime import required_cli_bridges


def test_knows_which_signed_in_cli_bridges_each_evaluation_table_needs() -> None:
    assert required_cli_bridges("models.evaluation-cli-gpt.yaml") == ("codex",)
    assert required_cli_bridges("models.evaluation-cli-gpt-terra-coder-low.yaml") == (
        "codex",
    )
    assert required_cli_bridges("models.evaluation-cli-gpt-terra-coder-high.yaml") == (
        "codex",
    )
    assert required_cli_bridges("models.evaluation-cli-gpt-sol-coder-medium.yaml") == (
        "codex",
    )
    assert required_cli_bridges(
        "models.evaluation-cli-gpt-sol-adjudicator-high.yaml"
    ) == ("codex",)
    assert required_cli_bridges("models.evaluation-cli-claude.yaml") == ("claude",)
    assert required_cli_bridges("models.evaluation-cli-mixed.yaml") == (
        "claude",
        "codex",
    )


def test_refuses_an_unapproved_model_table_before_starting_a_runtime() -> None:
    with pytest.raises(ValueError, match="not an evaluation CLI model table"):
        required_cli_bridges("models.openai.yaml")
