from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from nabu_evals.optimizer import DEFAULT_BRIDGE_URL, DEFAULT_MODEL_TABLE
from nabu_evals.runtime import DragomanRuntime, RuntimeSettings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="run the native prompt development stack"
    )
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--chancery-bin", required=True)
    parser.add_argument("--dragoman-bin", required=True)
    parser.add_argument("--bridge-url", default=DEFAULT_BRIDGE_URL)
    parser.add_argument("--chancery-port", type=int, required=True)
    parser.add_argument("--model-table", default=DEFAULT_MODEL_TABLE)
    args = parser.parse_args()
    prompts = args.prompts.expanduser().resolve()
    output = Path(".context/dev-runtime").resolve()
    settings = RuntimeSettings(
        prompts=prompts,
        output=output,
        chancery_bin=args.chancery_bin,
        dragoman_bin=args.dragoman_bin,
        model_table=args.model_table,
        bridge_url=args.bridge_url,
    )
    with DragomanRuntime(settings) as dragoman:
        env = os.environ.copy()
        env.update(
            {
                "PORT": str(args.chancery_port),
                "RESPONSES_BASE_URL": f"http://127.0.0.1:{dragoman.port}",
                "ENV": "development",
            }
        )
        command = [
            "watchexec",
            "-q",
            "-e",
            "md,yaml",
            "-r",
            "--watch",
            str(prompts / "config"),
            "--",
            args.chancery_bin,
            "--config",
            str(prompts / "config"),
            "--models",
            args.model_table,
            "serve",
        ]
        raise SystemExit(subprocess.call(command, cwd=prompts, env=env))


if __name__ == "__main__":
    main()
