from __future__ import annotations

import json
from pathlib import Path

from nabu_evals.cli import main


def test_report_writes_a_png_for_a_completed_campaign(tmp_path: Path) -> None:
    run = tmp_path / "campaign"
    development = run / "development"
    development.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps({"kind": "evaluation-campaign", "status": "complete"}),
        encoding="utf-8",
    )
    (development / "scores.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {"index": 0, "score": 0.42, "is_seed": True},
                    {"index": 1, "score": 0.58, "is_best": True},
                ],
                "best_index": 1,
            }
        ),
        encoding="utf-8",
    )
    (run / "comparison.json").write_text(
        json.dumps(
            {
                "baseline_mean_f1": 0.40,
                "winner_mean_f1": 0.55,
                "accepted": True,
            }
        ),
        encoding="utf-8",
    )

    main(["report", str(run)])

    image = run / "evaluation-report.png"
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
