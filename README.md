# nabu-evals

Automatic, deterministic prompt evaluation and proposal generation for Nabu qualitative coding. The optimizer runs the real frontend production pipeline and never modifies the source prompt with its proposal.

## 📋 Requirements

- Python 3.14 and `uv`
- The linked `nabu-frontend` and `nabu-prompts` checkouts
- Native `chancery` and `dragoman` binaries
- A signed-in Codex bridge on port 8084; start it with `make codex-bridge`

Install the locked Python environment with `uv sync`.

## 🚀 Usage

Run one closed optimization loop against one or more already-prepared gold roots:

```sh
make optimize ARGS="/path/to/gold-small --frontend /path/to/nabu-frontend --prompts /path/to/nabu-prompts --output /new/output --chancery-bin /path/to/chancery"
```

Measure an unchanged coding configuration—with no reflection, proposal, or source-prompt edit—before comparing system variants:

```sh
make evaluate ARGS="/path/to/gold-a /path/to/gold-b --frontend /path/to/nabu-frontend --prompts /path/to/nabu-prompts --output /new/output --chancery-bin /path/to/chancery"
```

The resulting `evaluation.json` records the exact coding profile, CLI model table, source-prompt hash, evaluated-guidance hash, per-root scores, requests, and frontend invocations. Use this command for model, reasoning, voter, and adjudication experiments; do not use `optimize` with zero proposals as a substitute. To test a deliberately written general instruction without changing the source prompt, supply `--guidance-file /path/to/candidate.md`; it is validated against the evaluated roots and its hash is recorded.

For a fast transport or hypothesis check, add `--coverage-probe-documents COUNT`. The probe deterministically selects no more than that many documents per supplied root by gold-label coverage and annotation count only—never by corpus prose or a model result—and records the exact selected filenames and a selection-specific hash. The coding stage still receives every sentence of each selected document. A probe is a rejection gate, not evidence for promotion.

Run a campaign when development and protected comparison roots are available:

```sh
make campaign ARGS="--development-root /path/to/development-a --development-root /path/to/development-b --comparison-root /path/to/comparison-a --comparison-root /path/to/comparison-b --frontend /path/to/nabu-frontend --prompts /path/to/nabu-prompts --output /new/output --chancery-bin /path/to/chancery"
```

The campaign runs the existing optimizer only on development roots, then fully re-scores every retained candidate over every development root before choosing the development winner. GEPA's internal minibatch score is retained only as diagnostic metadata; it cannot select a winner. The campaign scores that winner and the baseline on comparison roots, accepting it only when mean comparison F1 rises and no comparison root regresses. If the baseline wins on development, `comparison.json` records `candidate_compared: false` and the protected pass establishes only a baseline. `selected-coding-guidance.md` holds the accepted candidate or the retained baseline; the source prompt remains unchanged. Use `--coverage-probe-documents COUNT` for a bounded discovery campaign; it projects both development and comparison roots deterministically and records the exact selections, so a probe result is never promoted as full-corpus evidence.

Every run records its coding profile. Both profiles deliberately pass every supplied document to coding: retrieval and semantic filtering are disabled because they are cost controls, not the behavior under test. The default `single-coder-direct` profile measures one independent `voter-one` pass. `two-voter-adjudicated` changes only one system variable: it adds `voter-two` and adjudication. Never compare scores across profiles; compare a baseline and candidate within the same profile.

After a completed campaign, render a portable summary image:

```sh
uv run nabu-evals report /path/to/campaign-output
```

This writes `evaluation-report.png` beside the run. Its left chart shows every candidate's development score; its right chart shows the original prompt versus the development winner on the protected comparison set, and whether that winner was selected. Use `--output /path/to/report.png` to write it elsewhere.

Audit any stored scoring artifacts before treating a score change as a product improvement:

```sh
uv run nabu-evals audit /path/to/run-directory
```

The audit does not rerun coding or alter artifacts. It keeps candidate/root artifacts separate and reports exact and partial same-code spans, wrong-code annotations at an overlapping location, annotations with no overlapping counterpart, resolver errors, and a span-agnostic document-level code-presence diagnostic. Modern artifacts also expose count-only pipeline stages: candidates, voter selections, consensus, adjudication, and final decisions. It describes score mechanics only; it does not claim that a disputed gold label is semantically right. Use `--format json --output /path/to/audit.json` for a machine-readable record.

Quantify model-run variation from already-completed evaluations before treating a small score delta as a gain:

```sh
uv run nabu-evals stability /path/to/repeat-a /path/to/repeat-b
```

This command never reruns coding. It accepts only two or more completed fixed evaluations with the same CLI model table, coding profile, evaluated guidance, and exact selected-root manifests. It reports the observed range and sample standard deviation per root, explicitly not human inter-rater agreement or a significance test. Older artifacts with an explicit source-prompt-tree hash are admitted only as `legacy-source-tree` provenance.

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

Evaluation runs accept only dedicated, signed-in CLI tables: the moderate GPT control, GPT tables that change only `voter-one` to Terra-low, Terra-high, or Sol-medium, a table that changes only the existing adjudicator to Sol-high, Claude, or a moderate cross-provider Claude+GPT pair. The default GPT table uses `gpt-5.6-terra` for both voters and the adjudicator; the mixed table gives `voter-one` Claude Sonnet and `voter-two` GPT Terra. Reflection uses the local Codex CLI. No evaluation path silently falls back to an API-key-backed provider or upgrades every call to the largest model.

## 💻 Commands

```sh
make dev       # native Dragoman plus watched Chancery for manual prompt work
make check     # Ruff and Pyright
make test      # pytest
make optimize ARGS="..."
make evaluate ARGS="..."
make campaign ARGS="..."
make codex-bridge  # signed-in Codex endpoint on 127.0.0.1:8084
make report ARGS="/path/to/campaign-output"
make audit ARGS="/path/to/run-directory"
make stability ARGS="/path/to/repeat-a /path/to/repeat-b"
uv run nabu-evals generate <source> ...
```

`make dev` reads `PROMPTS`, `CHANCERY`, `DRAGOMAN`, `BRIDGE_URL`, `CHANCERY_PORT`, and `MODEL_TABLE` overrides. Automatic optimization uses immutable candidate-specific Chancery processes instead of the watched development process.

## 🏗️ Scoring

Gold and predicted annotations resolve to production sentence ranges. Same-code ranges receive maximum-weight one-to-one matches at every positive intersection-over-union. The primary score is soft micro-F1 within a root; scores are averaged across roots so each supplied root has equal weight. Exact-range and IoU-at-least-0.5 F1 remain diagnostics.

The configured signed-in CLI reflection model sees bounded, anonymized deterministic diagnostics and proposes general replacement guidance. It is not the judge. Proposals containing source identifiers or copied gold/codebook material are rejected, with one formatting repair attempt.

## 🧪 Verification

```sh
make check
make test
```

The outside-in CLI test uses fake model/runtime processes to verify the two-candidate, multi-root lifecycle without provider calls.
