from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _write_gold_root(root: Path, *, code: str, body: str) -> None:
    (root / "corpus").mkdir(parents=True)
    (root / "codes").mkdir()
    (root / "framework.md").write_text("Framework\n", encoding="utf-8")
    (root / "codes" / f"{code}.md").write_text(
        "```json-callout\n"
        + json.dumps(
            {
                "id": code,
                "type": "note",
                "title": "Relevant passage",
                "content": "Select relevant passages.",
                "color": "blue",
                "collapsed": False,
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )
    (root / "corpus" / "document.md").write_text(
        body
        + "\n\n```json-annotations\n"
        + json.dumps(
            {
                "annotations": [
                    {
                        "text": body,
                        "reason": "Gold passage",
                        "code": code,
                        "actor": "gold",
                    }
                ]
            }
        )
        + "\n```\n",
        encoding="utf-8",
    )


def _executable(path: Path, source: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
    path.chmod(0o755)
    return path


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true, "account": "test@example.com"}')

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_campaign_scores_development_winner_on_protected_roots(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    comparison = tmp_path / "comparison"
    _write_gold_root(first, code="code-a", body="First numbered sentence.")
    _write_gold_root(second, code="code-b", body="Second numbered sentence.")
    _write_gold_root(comparison, code="code-c", body="Comparison numbered sentence.")
    (second / "corpus" / "second.md").write_text(
        (second / "corpus" / "document.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend"
    prompts = tmp_path / "prompts"
    frontend.mkdir()
    guidance = prompts / "config" / "deep-analysis-filter"
    guidance.mkdir(parents=True)
    (guidance / "coding-guidance.md").write_text(
        "Baseline coding guidance.\n",
        encoding="utf-8",
    )
    (guidance / "index.md").write_text(
        "---\nmodel: voter-one\n---\nFixed contract.\n\n[coding-guidance.md]\n",
        encoding="utf-8",
    )
    (prompts / "config" / "models.codex.yaml").write_text(
        "models:\n  voter-one:\n    model: fake/model\n", encoding="utf-8"
    )
    (prompts / "dragoman.yaml").write_text(
        "mode: override\ncodex:\n  endpoint: http://host.docker.internal:8083/v1\n"
        "  protocol: openai-responses\n  auth: CODEX_BRIDGE_KEY\n",
        encoding="utf-8",
    )
    events = tmp_path / "events.jsonl"
    runtime_source = f"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
events = {str(events)!r}
kind = os.path.basename(sys.argv[0])
if '--version' in sys.argv:
    print(kind + ' 1.0'); raise SystemExit(0)
if 'validate' in sys.argv:
    raise SystemExit(0)
port = int(os.environ.get('PORT', '0'))
if '--addr' in sys.argv:
    port = int(sys.argv[sys.argv.index('--addr') + 1].rsplit(':', 1)[1])
with open(events, 'a') as stream:
    stream.write(json.dumps({{'kind': kind, 'pid': os.getpid(), 'port': port, 'args': sys.argv[1:]}}) + '\\n')
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with open(events, 'a') as stream:
            stream.write(json.dumps({{'kind': kind + '-reflection', 'request': request}}) + '\\n')
        response = json.dumps({{'output': [{{'type': 'message', 'content': [{{'type': 'output_text', 'text': '```\\nEvaluate all definitions independently. Select the narrowest complete sentence range that carries enough evidence, enforce every inclusion and exclusion, and emit nothing when evidence is insufficient. Keep distinct passages separate and explain the decisive language briefly.\\n```'}}]}}]}}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(response))); self.end_headers(); self.wfile.write(response)
    def log_message(self, *args): pass
ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
"""
    chancery = _executable(tmp_path / "fake-chancery", runtime_source)
    dragoman = _executable(tmp_path / "fake-dragoman", runtime_source)
    npm = _executable(
        tmp_path / "fake-npm",
        f"""
import json, os, pathlib, sys
args = sys.argv
def value(flag): return args[args.index(flag) + 1]
output = pathlib.Path(value('--output')); output.parent.mkdir(parents=True, exist_ok=True)
job = json.loads(pathlib.Path(value('--input')).read_text())
candidate = pathlib.Path(value('--prompt-root'), 'deep-analysis-filter', 'coding-guidance.md').read_text()
documents = []
for source in job['documents']:
    annotations = []
    if 'Evaluate all definitions independently' in candidate:
        callout = json.loads(job['dimensions'][0]['markdown'].split('\\n', 1)[1].rsplit('\\n```', 1)[0])
        annotations = [{{'text': source['markdown'].strip(), 'reason': 'fake', 'code': callout['id'], 'actor': 'fake'}}]
    documents.append({{
      'path': source['path'], 'status': 'success' if annotations else 'empty',
      'annotationCount': len(annotations), 'warnings': [], 'failures': [],
      'generatedMarkdown': source['markdown'] + '\\n```json-annotations\\n' + json.dumps({{'annotations': annotations}}) + '\\n```\\n'
    }})
result = {{
  'documents': documents, 'latencyMs': 1, 'retries': 0,
  'requests': [{{'endpoint': '/deep-analysis-filter.voter-one'}}]
}}
output.write_text(json.dumps(result))
with open({str(events)!r}, 'a') as stream:
    stream.write(json.dumps({{'kind': 'npm', 'gateway': value('--gateway'), 'documents': len(job['documents'])}}) + '\\n')
""",
    )
    output = tmp_path / "run"
    executable = shutil.which("nabu-evals")
    assert executable is not None
    bridge = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()

    completed = subprocess.run(
        [
            executable,
            "campaign",
            "--development-root",
            str(first),
            "--development-root",
            str(second),
            "--comparison-root",
            str(comparison),
            "--frontend",
            str(frontend),
            "--prompts",
            str(prompts),
            "--output",
            str(output),
            "--chancery-bin",
            str(chancery),
            "--dragoman-bin",
            str(dragoman),
            "--npm-bin",
            str(npm),
            "--bridge-url",
            f"http://127.0.0.1:{bridge.server_port}",
            "--per-root-timeout",
            "30",
            "--total-timeout",
            "120",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": "/usr/bin"},
    )
    bridge.shutdown()
    thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert [root["name"] for root in run["development_roots"]] == ["first", "second"]
    assert [root["name"] for root in run["comparison_roots"]] == ["comparison"]
    assert run["status"] == "complete"
    recorded = [
        json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()
    ]
    dragoman_events = [event for event in recorded if event["kind"] == "fake-dragoman"]
    chancery_events = [event for event in recorded if event["kind"] == "fake-chancery"]
    reflection_events = [
        event for event in recorded if event["kind"] == "fake-dragoman-reflection"
    ]
    npm_events = [event for event in recorded if event["kind"] == "npm"]
    assert len(dragoman_events) == 2
    runtime_config = (output / "development/runtime/dragoman.yaml").read_text(
        encoding="utf-8"
    )
    assert f"http://127.0.0.1:{bridge.server_port}/v1" in runtime_config
    assert len(chancery_events) == 4
    assert len({event["pid"] for event in chancery_events}) == 4
    assert len({event["port"] for event in chancery_events}) == 4
    assert all("models.codex.yaml" in event["args"] for event in chancery_events)
    assert len(reflection_events) == 1
    assert reflection_events[0]["request"]["model"] == "codex/gpt-5.6-sol"
    assert (
        "Comparison numbered sentence." not in reflection_events[0]["request"]["input"]
    )
    assert len(npm_events) == 6
    assert {event["documents"] for event in npm_events} == {1, 2}
    assert (output / "development/candidates/baseline/coding-guidance.md").is_file()
    assert (output / "development/candidates/proposal-1/coding-guidance.md").is_file()
    assert (output / "development/scores.json").is_file()
    scores = json.loads(
        (output / "development/scores.json").read_text(encoding="utf-8")
    )
    assert [candidate["score"] for candidate in scores["candidates"]] == [0, 1]
    assert scores["best_index"] == 1
    assert scores["proposal_indices"] == [1]
    comparison_result = json.loads(
        (output / "comparison.json").read_text(encoding="utf-8")
    )
    assert comparison_result["winner_index"] == 1
    assert comparison_result["accepted"] is True
    assert [score["root"] for score in comparison_result["roots"]] == ["comparison"]
    selected = (output / "selected-coding-guidance.md").read_text(encoding="utf-8")
    assert selected.startswith("Evaluate all definitions independently")
