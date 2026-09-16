# Evaluation flows

These diagrams explain how the coding-guidance optimizer evaluates and improves a prompt. A **gold root** is a benchmark project in the same shape the application normally reads: shared framework context, individual code definitions, and annotated corpus documents.

## Figure 1: The optimization loop

This is the top-level mental model: the evaluator searches for better coding guidance by measuring a baseline and successive replacements against the gold roots. Each measurement is preserved as an artifact, while bounded error evidence informs the next proposal. The candidate-proposal budget is the stopping rule; the result is the best measured candidate rather than an automatically proven optimum. [Figure 2](#figure-2-where-the-loops-artifacts-live) places these named pieces in their repositories and services.

```mermaid
flowchart TD
  baseline[("Baseline coding guidance")]
  candidate["Candidate guidance"]
  evaluate["Run every gold root\nthrough the production coding pipeline"]
  score["Aggregate soft F1\nand deterministic diagnostics"]
  budget{"Candidate proposal\nbudget remaining?"}
  feedback["Bounded diagnostic feedback\nper-label errors and span examples"]
  reflection["Opus reflection"]
  proposal["Replacement coding guidance"]
  artifacts[("Persisted run artifacts\nscores, diagnostics, diffs")]
  best["Best candidate\nand score summary"]

  baseline --> candidate
  candidate --> evaluate
  evaluate --> score
  score -->|record each evaluation| artifacts
  score --> budget
  budget -->|yes| feedback
  feedback --> reflection
  reflection --> proposal
  proposal --> candidate
  budget -->|no| best

  classDef candidateNode fill:#f3e8ff,stroke:#7e22ce,color:#581c87
  classDef evaluationNode fill:#dcfce7,stroke:#16a34a,color:#14532d
  classDef controlNode fill:#fef3c7,stroke:#d97706,color:#78350f
  classDef artifactNode fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
  class baseline,candidate,proposal candidateNode
  class evaluate,score,feedback,reflection evaluationNode
  class budget controlNode
  class artifacts,best artifactNode
```

## Figure 2: Where the loop's artifacts live

[Figure 1](#figure-1-the-optimization-loop) establishes the roles; this map establishes their ownership. The benchmark’s files are regular coding inputs for the frontend, while nabu-evals supplies orchestration and records results. Prompt source material and candidate copies are served through the normal prompt/runtime path, so each score reflects the production coding pipeline. With those boundaries in mind, [Figure 3](#figure-3-inside-run-every-gold-root) follows one evaluation through that path.

```mermaid
flowchart LR
  subgraph gold["Gold roots"]
    root[("Benchmark project")]
    framework["framework.md\nshared coding context"]
    codes["codes/*.md\ncode definitions"]
    corpus["corpus/*.md\ncorpus and gold annotations"]
    root --- framework
    root --- codes
    root --- corpus
  end

  subgraph evals["nabu-evals"]
    optimizer["Optimizer"]
    candidate["Candidate prompt copies"]
    artifacts["Run artifacts\nmanifests, scores, diagnostics, diffs"]
  end

  subgraph prompts["nabu-prompts"]
    source["Source prompt configuration\nand model tables"]
    guidance["Reusable coding guidance"]
  end

  subgraph frontend["nabu-frontend"]
    batch["Batch evaluator"]
    pipeline["Deep-analysis coding pipeline\nframework and dimension sources"]
    comparison["Annotation comparison\nand metrics"]
  end

  subgraph runtime["External runtime services"]
    chancery["Chancery"]
    dragoman["Dragoman"]
    bridge["Claude bridge and model"]
  end

  root -->|validate and record| optimizer
  root -->|load normal source files| batch
  source -->|copy| candidate
  guidance -->|replace| candidate
  optimizer -->|create| candidate
  candidate -->|serve| chancery
  optimizer -->|run| batch
  batch -->|invoke| pipeline
  pipeline -->|generated annotations| comparison
  comparison -->|metrics and diagnostics| artifacts
  pipeline -->|coding request| chancery
  chancery -->|provider request| dragoman
  dragoman -->|model request| bridge

  classDef goldNode fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
  classDef evalNode fill:#f3e8ff,stroke:#7e22ce,color:#581c87
  classDef frontendNode fill:#dcfce7,stroke:#16a34a,color:#14532d
  classDef runtimeNode fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
  classDef artifactNode fill:#fef3c7,stroke:#d97706,color:#78350f
  class root,framework,codes,corpus goldNode
  class optimizer,candidate evalNode
  class batch,pipeline frontendNode
  class chancery,dragoman,bridge runtimeNode
  class artifacts,comparison artifactNode

  linkStyle 0,1,2 stroke:#94a3b8,stroke-width:1px
  linkStyle 3,4 stroke:#0284c7,stroke-width:2px
  linkStyle 5,6,7,8,9 stroke:#7e22ce,stroke-width:2px
  linkStyle 10,11 stroke:#16a34a,stroke-width:2px
  linkStyle 12 stroke:#d97706,stroke-width:2px
  linkStyle 13,14,15 stroke:#dc2626,stroke-width:2px
```

## Figure 3: Inside “run every gold root”

[Figure 2](#figure-2-where-the-loops-artifacts-live) locates the participants; this sequence zooms into one candidate evaluation. The frontend loads the benchmark’s framework and code files as ordinary source files, prepares its corpus, and sends the coding request through the normal model gateway. The scorer compares the returned annotations with gold annotations and returns the metrics and diagnostic evidence that drive the next proposal in the optimization loop.

```mermaid
sequenceDiagram
  participant E as nabu-evals optimizer
  participant F as frontend batch evaluator
  participant C as Chancery
  participant D as Dragoman
  participant M as Model
  participant S as Gold scorer
  participant O as Opus reflection

  loop Baseline and candidate evaluations
    rect rgb(243, 232, 255)
      Note over E,F: Candidate setup
      E->>C: Serve candidate prompt configuration
      E->>F: Run batch with gold root and gateway
    end
    rect rgb(220, 252, 231)
      Note over F,M: Production coding execution
      F->>F: Load framework.md and codes/*.md as source files
      F->>F: Prepare corpus documents for inference
      F->>C: Request deep-analysis-filter voter-one
      C->>D: Translate model request
      D->>M: Send provider request
      M-->>D: Coder response
      D-->>C: Provider response
      C-->>F: Parsed coding response
      F->>F: Write generated annotation blocks
    end
    rect rgb(224, 242, 254)
      Note over E,O: Score and improve guidance
      F->>S: Generated annotations and gold annotations
      S-->>E: F1 metrics and diagnostics
      E->>O: Current guidance and bounded feedback
      O-->>E: Replacement coding guidance
    end
  end
```
