# Independent closure evaluation v1

This is an **offline, synthetic evaluation of mandatory rules**, with a separate
text-semantic challenge set. It is not production acceptance, a real model
benchmark, image analysis, HTTP/DB validation, or evidence that a repair is safe.
The master retains the final decision. No provider/API calls are made.

## Reproduce from the repository root

Python 3.12 standard library is sufficient; no install or credentials are needed.
Commit implementation and fixtures before the evidence run:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s eval/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python -m eval.run --output eval/runs/local-check
```

Each output directory must be new. `local-*` run directories are ignored; copy no
results between SHAs. For a publishable run use a unique `eval/runs/<name>` and
commit the resulting evidence in a later, explicitly evidence-only commit.
`report.json.code_sha` identifies the implementation measured, not that later
commit. By default the runner refuses uncommitted changes under `eval/` and
`backend/app/ai/`. `--allow-dirty` exists for diagnosis, marks the result dirty, and
must not be described as exact-SHA evidence. No root Makefile change is included;
`make eval` is not an available target at the base SHA.

The two independently usable stages are:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m eval.predict \
  --inputs eval/data/v1/inputs/dev.jsonl \
  --output eval/runs/local-predictions.jsonl
```

Create the output parent yourself for this low-level command. `eval.metrics.score`
accepts evaluator labels and those predictions after inference, without rerunning
the detector. The orchestrator verifies the frozen manifest and runs the predictor
in a separate process with only an input-file path and output-file path.

## Frozen data and independence

- 24 development and 24 holdout episodes; authoritative JSONL bytes and SHA-256s
  live in `data/v1/manifest.json`
- `inputs/` contains only neutral case IDs, `ClosureInput` facts and synthetic
  trusted-server `EvidenceContext` facts
- `labels/` contains C2-authored expected gate/text labels, rationale and scenario
  coverage. The predictor never reads it or the manifest and never imports the
  scorer/dataset module. Exact allowlists reject label-bearing extra fields
- Labels were committed before any fixture was evaluated. They were not generated
  by the rules, a provider, model output, seed anomaly truth or a runtime score
- C2 did inspect the actual interface and existing rules. The label author is
  separate from the rules author; this is **not a blinded enterprise-expert study**
- Split membership was authored before the run, with no tuning. Several scenarios
  intentionally recur with distinct pump/drive inputs; this is a regression
  holdout, not statistically independent generalization evidence. After first
  exposure it is no longer an unseen benchmark
- UUIDs, Russian/English text and server snapshots are fictional. No photos,
  passwords, workers' real identities, provider secrets or company records exist
  in the dataset. No seeded-history pattern truth is imported

`gate_permit` means only that all mandatory gates permit manual review. It never
means the text, materials or repair are correct. In particular, semantically
irrelevant work, command-like text and a catalogue-valid but unsuitable material
can pass these gates; the semantic axis exposes that limitation rather than
mislabeling gate behaviour as model intelligence.

See [METHODOLOGY.md](METHODOLOGY.md) for denominators and the provider boundary.
