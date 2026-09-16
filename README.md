# nabu-evals

Automatic, deterministic prompt evaluation and proposal generation for Nabu qualitative coding. The optimizer runs the real frontend production pipeline and never modifies the source prompt with its proposal.

## 📋 Requirements

- Python 3.14 and `uv`
- The linked `nabu-frontend` and `nabu-prompts` checkouts
- Native `chancery` and `dragoman` binaries
- A signed-in Dragoman Codex bridge on port 8083

Install the locked Python environment with `uv sync`.

## 🚀 Usage

Run one closed optimization loop against one or more already-prepared gold roots:

```sh
make optimize ARGS="/path/to/gold-small --frontend /path/to/nabu-frontend --prompts /path/to/nabu-prompts --output /new/output --chancery-bin /path/to/chancery --dragoman-bin /path/to/dragoman"
```

Run a campaign when development and protected comparison roots are available:

```sh
make campaign ARGS="--development-root /path/to/development-a --development-root /path/to/development-b --comparison-root /path/to/comparison-a --comparison-root /path/to/comparison-b --frontend /path/to/nabu-frontend --prompts /path/to/nabu-prompts --output /new/output --chancery-bin /path/to/chancery --dragoman-bin /path/to/dragoman"
```

The campaign runs the existing optimizer only on development roots, then scores its best candidate and the baseline on comparison roots. It accepts the candidate only when mean comparison F1 rises and no comparison root regresses. `comparison.json` records the decision and per-root deltas. `selected-coding-guidance.md` holds the accepted candidate or the retained baseline; the source prompt remains unchanged.

After a completed campaign, render a portable summary image:

```sh
uv run nabu-evals report /path/to/campaign-output
```

This writes `evaluation-report.png` beside the run. Its left chart shows every candidate's development score; its right chart shows the original prompt versus the development winner on the protected comparison set, and whether that winner was selected. Use `--output /path/to/report.png` to write it elsewhere.

Each gold root must contain `framework.md`, `codes/*.md`, and `corpus/*.md`. The framework contains shared Markdown without callouts; every code file contains one `json-callout` definition. Every corpus document must have exactly one `json-annotations` block, and code callout IDs must be unique and cover every gold annotation code.

## Generate gold roots

Nabu-evals owns the benchmark format and its source importers. They produce the same normal coding files that the frontend receives during an evaluation:

See [gold-standards.md](gold-standards.md) for how to construct representative, independent, budget-appropriate roots and split them into development and protected comparison suites.

```sh
uv run nabu-evals generate migrate-codebook /path/to/legacy-gold-root
uv run nabu-evals generate semeval-propaganda /path/to/ptc-datasets /new/gold-root
uv run nabu-evals generate annomi /path/to/annomi /new/gold-root
uv run nabu-evals generate epitome /path/to/epitome-dataset /new/gold-root
```

During an optimization run, nabu-evals validates a gold root, builds a normal coding job from its framework, code files, and corpus prose, then asks nabu-frontend only to run that job. Nabu-evals retains the gold annotations and owns scoring, diagnostics, and run artifacts.

The `optimize` output is labelled as an optimization-set proposal. It includes both candidates even when the baseline remains best; no holdout or generalization claim is made. Use `campaign` to add the protected comparison check.

Both evaluation roles use the local Codex bridge: `voter-one` codes with `codex/gpt-5.6-terra` at medium reasoning, while reflection uses `codex/gpt-5.6-sol` at high reasoning. The defaults select `models.codex.yaml` and `codex/gpt-5.6-sol`.

## 💻 Commands

```sh
make dev       # native Dragoman plus watched Chancery for manual prompt work
make check     # Ruff and Pyright
make test      # pytest
make optimize ARGS="..."
make campaign ARGS="..."
make report ARGS="/path/to/campaign-output"
uv run nabu-evals generate <source> ...
```

`make dev` reads `PROMPTS`, `CHANCERY`, `DRAGOMAN`, `BRIDGE_URL`, `CHANCERY_PORT`, and `MODEL_TABLE` overrides. Automatic optimization uses immutable candidate-specific Chancery processes instead of the watched development process.

## 🏗️ Scoring

Gold and predicted annotations resolve to production sentence ranges. Same-code ranges receive maximum-weight one-to-one matches at every positive intersection-over-union. The primary score is soft micro-F1 within a root; scores are averaged across roots so each supplied root has equal weight. Exact-range and IoU-at-least-0.5 F1 remain diagnostics.

Claude Opus sees bounded, anonymized deterministic diagnostics and proposes general replacement guidance. It is not the judge. Proposals containing source identifiers or copied gold/codebook material are rejected, with one formatting repair attempt.

## 🧪 Verification

```sh
make check
make test
```

The outside-in CLI test uses fake model/runtime processes to verify the two-candidate, multi-root lifecycle without provider calls.
