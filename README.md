# nabu-evals

Automatic, deterministic prompt evaluation and proposal generation for Nabu qualitative coding. The optimizer runs the real frontend production pipeline and never modifies the source prompt with its proposal.

## 📋 Requirements

- Python 3.14 and `uv`
- The linked `nabu-frontend` and `nabu-prompts` checkouts
- Native `chancery` and `dragoman` binaries
- A signed-in Dragoman Claude bridge on port 8082
- A signed-in `claude` CLI for Opus reflection

Install the locked Python environment with `uv sync`.

## 🚀 Usage

Run one closed optimization loop against one or more already-prepared gold roots:

```sh
make optimize ARGS="/path/to/gold-small --frontend /path/to/nabu-frontend --prompts /path/to/nabu-prompts --output /new/output --chancery-bin /path/to/chancery --dragoman-bin /path/to/dragoman"
```

Each gold root must contain `codebook.md` and `corpus/*.md`. Every corpus document must have exactly one `json-annotations` block, and codebook callout IDs must be unique and cover every gold annotation code.

The output is labelled as an optimization-set proposal. It includes both candidates even when the baseline remains best; no holdout or generalization claim is made.

`--reflection-model` defaults to the Claude CLI `opus` alias. Set an exact Opus model ID when reproducible model selection is required.

## 💻 Commands

```sh
make dev       # native Dragoman plus watched Chancery for manual prompt work
make check     # Ruff and Pyright
make test      # pytest
make optimize ARGS="..."
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
