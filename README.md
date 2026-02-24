# Data Inspector (OO + modular)

This is a heuristic-based Python pipeline that:

- **Detects** common data-ish file types (CSV/TSV/other delimited text, JSON, JSONL, YAML, XML, HTML tables, XLSX, SQLite, ZIP, NPZ, gzip, bzip2, plus binary fallback).
- **Summarizes structure** and prints it to the terminal.
- **Runs ML-readiness diagnostics** (the 12 `vital` checklist categories) when a tabular profile can be derived.

It is **deliberately heuristic**: it tries to be useful fast, not to be perfect in every weird edge case humans invent.

## Documentation

- Operator runbook: `OPERATOR_README.md`
- Engineer architecture guide: `ENGINEER_README.md`
- Contract specs: `contracts/README.md`

## End-to-end loop test

```bash
python3 scripts/test_feedback_loop_e2e.py
```

## Quick start

From the project root:

```bash
python3 inspect_data.py sample_data --recursive
```

Single file:

```bash
python3 inspect_data.py sample_data/people.csv
python3 inspect_data.py sample_data/table.xlsx
python3 inspect_data.py sample_data/data.sqlite
python3 inspect_data.py sample_data/metrics.csv.gz
python3 inspect_data.py sample_data/archive.zip
python3 inspect_data.py sample_data/people.csv --target-col is_active --time-col signup_date
```

## Install deps (optional)

```bash
pip install -r requirements.txt
```

If you don't install pandas, the inspector will still work, but you'll lose nicer table summaries and HTML table extraction.

## ML diagnostics

Diagnostics are heuristic and intentionally robust over perfect:

- They run as a second stage after file detection + inspection.
- They produce a per-file `vital_supported: X/12` summary.
- For ambiguous items (target/task/split/metric), pass hints:
  - `--target-col`
  - `--task-hint`
  - `--time-col`
  - `--group-col`
  - `--split-col`
  - `--id-cols`
  - `--metric`
- Export inferred assumptions for user verification:
  - `--assumptions-out ./out/assumptions.json`
  - `--diagnostic-bundle-out ./out/diagnostic_bundle.json`
  - `--strict-assumptions` (exits non-zero if unresolved assumptions remain)
- Disable diagnostics with `--no-diagnostics`.

## Model recommender

Generate architecture recommendations from diagnostics:

```bash
python3 recommend_models.py \
  --diagnostic-in ./out/diagnostic_bundle.json \
  --recommendation-out ./out/recommendation_bundle.json
```

The recommender also accepts legacy assumptions JSON and can normalize it first:

```bash
python3 recommend_models.py \
  --diagnostic-in ./out/assumptions.json \
  --normalized-diagnostic-out ./out/diagnostic_bundle.json \
  --recommendation-out ./out/recommendation_bundle.json
```

## Generate sample data

```bash
python3 scripts/generate_test_data.py
```

It writes files into `sample_data/`.
Generated diagnostics/recommendation artifacts are written under `tmp/` by convention.

## Project layout

- `ingestor_island/`
  Ingestion/diagnostics island runtime (`ingestor_island/src/data_inspector`).
- `collator_island/`
  Collator/pipeline assembly prototype island.
- `model_selector_island/`
  Model recommendation heuristic island (scaffolded).
- `contracts/`
  Shared JSON contracts/schemas between islands.
- `ingestor_island/src/data_inspector/core/`
  Detection + engine + shared dataclasses.
- `ingestor_island/src/data_inspector/inspectors/`
  One inspector per file type.
- `ingestor_island/src/data_inspector/printers/`
  Output formatting (terminal printer).
- `src/data_inspector/`
  Compatibility shim for legacy imports/entry points.
- `scripts/`  
  Utility scripts (sample data generator).
- `sample_data/`  
  Pre-generated test files.

## Safety

Pickle files are **detected** but not unpickled unless you pass `--unsafe-unpickle`.
