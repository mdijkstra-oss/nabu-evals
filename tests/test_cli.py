from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _write_gold_root(root: Path, *, code: str, body: str) -> None:
    (root / "corpus").mkdir(parents=True)
    (root / "codebook.md").write_text(
        "Framework\n\n"
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


def test_optimize_accepts_multiple_uniform_gold_roots(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_gold_root(first, code="code-a", body="First numbered sentence.")
    _write_gold_root(second, code="code-b", body="Second numbered sentence.")
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
        "Judge each definition and select a minimal complete sentence span.\n",
        encoding="utf-8",
    )
    (guidance / "index.md").write_text(
        "---\nmodel: voter-one\n---\nFixed contract.\n\n[coding-guidance.md]\n",
        encoding="utf-8",
    )
    (prompts / "config" / "models.claude-cli.yaml").write_text(
        "models:\n  voter-one:\n    model: fake/model\n", encoding="utf-8"
    )
    (prompts / "dragoman.yaml").write_text(
        "mode: override\nclaude-cli:\n  endpoint: http://host.docker.internal:8082/v1\n"
        "  protocol: anthropic-messages\n  auth: CLAUDE_BRIDGE_KEY\n",
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
    stream.write(json.dumps({{'kind': kind, 'pid': os.getpid(), 'port': port}}) + '\\n')
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *args): pass
ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
"""
    chancery = _executable(tmp_path / "fake-chancery", runtime_source)
    dragoman = _executable(tmp_path / "fake-dragoman", runtime_source)
    claude = _executable(
        tmp_path / "fake-claude",
        f"""
import json, os, sys
with open({str(events)!r}, 'a') as stream:
    stream.write(json.dumps({{'kind': 'claude', 'pid': os.getpid()}}) + '\\n')
sys.stdin.read()
print('```\\nEvaluate all definitions independently. Select the narrowest complete sentence range that carries enough evidence, enforce every inclusion and exclusion, and emit nothing when evidence is insufficient. Keep distinct passages separate and explain the decisive language briefly.\\n```')
""",
    )
    npm = _executable(
        tmp_path / "fake-npm",
        f"""
import json, os, pathlib, sys
args = sys.argv
def value(flag): return args[args.index(flag) + 1]
output = pathlib.Path(value('--output')); output.mkdir(parents=True)
gold = pathlib.Path(value('--gold-dir'))
candidate = pathlib.Path(value('--prompt-root'), 'deep-analysis-filter', 'coding-guidance.md').read_text()
if 'Evaluate all definitions independently' in candidate:
    score = 0.1
else:
    score = 0.2 if gold.name == 'first' else 0.8
documents = []
for source in sorted((gold / 'corpus').glob('*.md')):
    (output / (source.stem + '.generated.md')).write_text(source.read_text())
    documents.append({{
      'name': source.name, 'status': 'success', 'annotationCount': 1,
      'goldAnnotationCount': 1, 'warnings': [], 'failures': [],
      'comparison': {{'matches': [], 'falsePositives': [], 'falseNegatives': [], 'errors': []}}
    }})
result = {{
  'documents': documents, 'outcomes': {{'success': len(documents), 'empty': 0, 'partial': 0, 'failed': 0, 'malformed': 0}},
  'complete': True, 'soft': {{'tp': score, 'fp': 1-score, 'fn': 1-score, 'precision': score, 'recall': score, 'f1': score}},
  'relaxed': {{'tp': 1, 'fp': 0, 'fn': 0, 'precision': 1, 'recall': 1, 'f1': 1}},
  'exact': {{'tp': 1, 'fp': 0, 'fn': 0, 'precision': 1, 'recall': 1, 'f1': 1}},
  'perCode': [], 'diagnostics': [], 'requests': [{{'endpoint': '/deep-analysis-filter.voter-one'}}],
  'endpoints': ['/deep-analysis-filter.voter-one']
}}
(output / 'results.json').write_text(json.dumps(result))
with open({str(events)!r}, 'a') as stream:
    stream.write(json.dumps({{'kind': 'npm', 'gateway': value('--gateway'), 'gold': gold.name}}) + '\\n')
""",
    )
    output = tmp_path / "run"
    bridge = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()

    completed = subprocess.run(
        [
            "nabu-evals",
            "optimize",
            str(first),
            str(second),
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
            "--claude-bin",
            str(claude),
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
    )
    bridge.shutdown()
    thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert [root["name"] for root in run["roots"]] == ["first", "second"]
    assert run["status"] == "complete"
    recorded = [
        json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()
    ]
    dragoman_events = [event for event in recorded if event["kind"] == "fake-dragoman"]
    chancery_events = [event for event in recorded if event["kind"] == "fake-chancery"]
    npm_events = [event for event in recorded if event["kind"] == "npm"]
    assert len(dragoman_events) == 1
    runtime_config = (output / "runtime/dragoman.yaml").read_text(encoding="utf-8")
    assert f"http://127.0.0.1:{bridge.server_port}/v1" in runtime_config
    assert len(chancery_events) == 2
    assert len({event["pid"] for event in chancery_events}) == 2
    assert len({event["port"] for event in chancery_events}) == 2
    assert len(npm_events) == 4
    assert {event["gold"] for event in npm_events} == {"first", "second"}
    assert (output / "candidates/baseline/coding-guidance.md").is_file()
    assert (output / "candidates/proposal-1/coding-guidance.md").is_file()
    assert (output / "scores.json").is_file()
    scores = json.loads((output / "scores.json").read_text(encoding="utf-8"))
    assert [candidate["score"] for candidate in scores["candidates"]] == [0.5, 0.1]
    assert scores["best_index"] == 0
    assert scores["proposal_indices"] == [1]
