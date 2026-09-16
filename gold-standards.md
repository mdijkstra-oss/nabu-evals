# Gold standards for qualitative-coding evaluation

This guide is for people and agents creating Nabu coding benchmarks. A good gold standard is a labelled, representative, independent coding task whose score is useful for deciding whether reusable coding guidance improved.

See [README.md](README.md) for the command and file format, and [eval-flows.md](eval-flows.md) for the optimizer lifecycle.

## 🧭 What a gold root measures

One root is one coherent coding task: shared context in `framework.md`, one code definition per file in `codes/`, and labelled documents in `corpus/`. Nabu sends the framework, definitions, and unannotated document prose through the normal coding path, then scores generated annotations against retained gold.

The primary metric is sentence-range soft micro-F1. When several roots are supplied, each root has equal weight, irrespective of document count. Keep different coding schemes or source families in separate roots so each receives one meaningful vote.

## 🏗️ Root requirements

The loader requires:

- `framework.md`, at least one code file, and at least one corpus file;
- no `json-callout` blocks in the framework;
- exactly one valid `json-callout` per code file, with a unique non-empty ID;
- exactly one valid `json-annotations` block per corpus file;
- annotation `text`, `reason`, `code`, and `actor` strings, with every code defined by the root;
- at least one positive annotation in the root.

For the score to mean anything, gold annotation text must be an exact, resolvable excerpt of unchanged document prose. Record the intended coding policy, including exclusions and span breadth, in the framework or definitions. Keep genuine negative documents with empty annotation blocks: they measure false positives.

## 🎯 Development and protected comparison

Every source family should normally become two non-overlapping roots:

| Root | Used by | Purpose |
| --- | --- | --- |
| Development | Optimizer and reflection | Produce and rank prompt candidates. |
| Protected comparison | Candidate review only | Check whether the development winner also improves on unseen examples. |

The `optimize` command treats every supplied root as development. Do not pass comparison roots to it. The `campaign` command runs `optimize` on development roots, then scores the baseline and its winner on comparison roots; comparison text never reaches reflection. A candidate passes only when mean comparison F1 rises and no comparison root regresses.

Split by the real independence unit, never arbitrary excerpts: whole articles, transcripts, interviews, or original posts plus all their responses. Do not count a copied subset as independent gold. Record the split seed or the exact selected-file manifest.

Both halves need positives, negatives, common codes, and difficult cases. Rare codes that occur only once cannot independently measure improvement; do not duplicate their example to make the split look balanced.

The development battery is deliberately small because it runs for every proposal. The protected comparison battery can be the same size or larger because it is run only for the baseline and the selected candidate. Keep an optional third, frozen release set only if the product needs a rarely-used final gate.

## ⚙️ Size from cost, not a corpus percentage

Do not put 70% of a huge corpus in development just because it is 70%. The evaluator codes every selected chunk for every candidate. It bypasses retrieval and semantic filtering, runs one coder, and packs at most 20 chunks and 3 code definitions per request.

For `K` coding chunks and `C` codes, the lower-bound request cost for one root and one candidate is:

```text
ceil(K / 20) × ceil(C / 3)
```

A document can produce several chunks, so measure rather than estimate from file count. With `P` proposals, baseline plus proposals cost at least:

```text
(P + 1) × sum(development-root request costs)
```

Retries add cost. The current defaults cap a root at 200 coding requests, the run at 100 frontend invocations, each root attempt at 30 minutes, and the whole run at two hours. An over-budget root makes the run fail.

Start with a fixed, diverse development battery that leaves headroom under those limits. Run a baseline-only calibration with `--max-candidate-proposals 0`, inspect its request counts and failures, then resize the battery before asking for a proposal. This measured cost—not a fixed document ratio—determines the development size.

## 📋 Creation checklist

- [ ] The root passes validation and its annotation excerpts resolve against document prose.
- [ ] It represents a distinct coding task or source family.
- [ ] Related documents and duplicates are kept on one split side.
- [ ] Development and comparison roots are reproducible and non-overlapping.
- [ ] Both have representative positives, negatives, common codes, and boundary cases.
- [ ] Development fits the measured request and time budget.
- [ ] Comparison was never supplied to optimization or reflection.

An optimization win proves only that the candidate improved on its development roots. A protected-comparison win is evidence of improvement on those unseen roots, not every possible qualitative-coding project.
