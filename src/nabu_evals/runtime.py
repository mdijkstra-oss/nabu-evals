from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Self


class RuntimeFailure(RuntimeError):
    """A candidate could not be evaluated because its runtime failed."""


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_health(
    url: str, process: subprocess.Popen[str], timeout: float = 15
) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeFailure(
                f"process exited with status {process.returncode}: {url}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(0.1)
    raise RuntimeFailure(f"health check timed out at {url}: {last_error}")


def preflight_health(url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status != 200:
                raise RuntimeFailure(
                    f"health check failed at {url}: HTTP {response.status}"
                )
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeFailure(f"health check failed at {url}: {error}") from error


def preflight_bridge(url: str) -> None:
    health = url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(health, timeout=3) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise RuntimeFailure(f"bridge preflight failed at {health}: {error}") from error
    if (
        response.status != 200
        or payload.get("ok") is not True
        or not payload.get("account")
    ):
        raise RuntimeFailure(f"{health} is not a signed-in bridge")


class ManagedProcess(AbstractContextManager["ManagedProcess"]):
    def __init__(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.env = env
        self.log_path = log_path
        self.process: subprocess.Popen[str] | None = None
        self._log: IO[str] | None = None

    def __enter__(self) -> Self:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=self.env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        return self

    @property
    def pid(self) -> int:
        if self.process is None:
            raise RuntimeError("process has not started")
        return self.process.pid

    def __exit__(self, *exc: object) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self._log is not None:
            self._log.close()


@dataclass(frozen=True)
class RuntimeSettings:
    prompts: Path
    output: Path
    chancery_bin: str
    dragoman_bin: str
    model_table: str
    bridge_url: str


class CandidateRuntime(AbstractContextManager["CandidateRuntime"]):
    def __init__(
        self,
        settings: RuntimeSettings,
        guidance: str,
        candidate_hash: str,
        name: str,
        dragoman_port: int,
    ) -> None:
        self.settings = settings
        self.guidance = guidance
        self.candidate_hash = candidate_hash
        self.name = name
        self.dragoman_port = dragoman_port
        self.port = free_port()
        self.directory = settings.output / "candidates" / name
        self.config = self.directory / "config"
        self.process: ManagedProcess | None = None

    def __enter__(self) -> Self:
        source_config = self.settings.prompts / "config"
        shutil.copytree(source_config, self.config)
        guidance_path = self.config / "deep-analysis-filter" / "coding-guidance.md"
        guidance_path.write_text(self.guidance.rstrip() + "\n", encoding="utf-8")
        (self.directory / "coding-guidance.md").write_text(
            self.guidance.rstrip() + "\n", encoding="utf-8"
        )
        validate = subprocess.run(
            [
                self.settings.chancery_bin,
                "--config",
                str(self.config),
                "--models",
                self.settings.model_table,
                "validate",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        (self.directory / "validation.log").write_text(
            validate.stdout + validate.stderr, encoding="utf-8"
        )
        if validate.returncode != 0:
            raise RuntimeFailure(f"Chancery rejected candidate {self.candidate_hash}")

        env = os.environ.copy()
        env.update(
            {
                "PORT": str(self.port),
                "RESPONSES_BASE_URL": f"http://127.0.0.1:{self.dragoman_port}",
                "ENV": "evaluation",
                "LOG_LEVEL": "info",
            }
        )
        self.process = ManagedProcess(
            [
                self.settings.chancery_bin,
                "--config",
                str(self.config),
                "--models",
                self.settings.model_table,
                "serve",
            ],
            cwd=self.settings.prompts,
            env=env,
            log_path=self.directory / "chancery.log",
        ).__enter__()
        try:
            assert self.process.process is not None
            wait_for_health(
                f"http://127.0.0.1:{self.port}/health", self.process.process
            )
        except BaseException:
            self.process.__exit__()
            raise
        (self.directory / "process.json").write_text(
            json.dumps(
                {
                    "pid": self.process.pid,
                    "port": self.port,
                    "candidate_hash": self.candidate_hash,
                    "command": self.process.command,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return self

    @property
    def gateway(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *exc: object) -> None:
        if self.process is not None:
            self.process.__exit__(*exc)


class DragomanRuntime(AbstractContextManager["DragomanRuntime"]):
    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self.port = free_port()
        self.process: ManagedProcess | None = None

    def __enter__(self) -> Self:
        preflight_bridge(self.settings.bridge_url)
        source = self.settings.prompts / "dragoman.yaml"
        config_text = source.read_text(encoding="utf-8")
        config_text = config_text.replace(
            "http://host.docker.internal:8083", self.settings.bridge_url.rstrip("/")
        )
        runtime_dir = self.settings.output / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config = runtime_dir / "dragoman.yaml"
        config.write_text(config_text, encoding="utf-8")
        env = os.environ.copy()
        env.setdefault("CLAUDE_BRIDGE_KEY", "local-evaluation")
        env.setdefault("CODEX_BRIDGE_KEY", "local-evaluation")
        self.process = ManagedProcess(
            [
                self.settings.dragoman_bin,
                "serve",
                "--addr",
                f"127.0.0.1:{self.port}",
                "--config",
                str(config),
            ],
            cwd=self.settings.prompts,
            env=env,
            log_path=runtime_dir / "dragoman.log",
        ).__enter__()
        try:
            assert self.process.process is not None
            wait_for_health(
                f"http://127.0.0.1:{self.port}/health", self.process.process
            )
        except BaseException:
            self.process.__exit__()
            raise
        (runtime_dir / "process.json").write_text(
            json.dumps(
                {
                    "pid": self.process.pid,
                    "port": self.port,
                    "command": self.process.command,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return self

    def __exit__(self, *exc: object) -> None:
        if self.process is not None:
            self.process.__exit__(*exc)
