# yoyoML

yoyoML is a repository for a heuristic data inspection and ML-readiness workflow. The installable package in this repo is `data-inspector`: it detects common dataset formats, summarizes structure, and emits diagnostics that help decide whether a dataset is usable for downstream ML work.

The design goal is practical triage, not perfect inference. This tool is meant to answer "what is this file, what shape is it in, and what obvious ML risks are already visible?" before you start training anything expensive.

## What it does

- Detects CSV, TSV, delimited text, JSON, JSONL, YAML, XML, HTML tables, XLSX, SQLite, ZIP, NPZ, compressed files, and binary fallbacks.
- Prints structural summaries directly in the terminal.
- Runs a 12-category ML-readiness diagnostic pass when tabular structure can be profiled.
- Exports normalized JSON bundles for downstream recommendation and feedback-loop tooling.

## Install

For package usage:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For repo-local script usage without installation:

```bash
pip install -r requirements.txt
```

## Quick Start

Inspect a single file from a repo checkout:

```bash
python3 inspect_data.py sample_data/people.csv
```

After installation, use the packaged CLI:

```bash
data-inspector sample_data/people.csv --target-col is_active --time-col signup_date
```

Inspect a directory recursively:

```bash
python3 inspect_data.py sample_data --recursive
```

Representative output:

```text
Detected: csv (confidence 95%)
Reason: Looks like delimited tabular text
Diagnostics:
  vital_supported: 11/12
  assumptions: auto_accept=1, verify_or_unresolved=5
```

## Before And After Examples

Before: point the inspector at an unfamiliar dataset to get a structural summary and first-pass diagnostic coverage.

```bash
python3 inspect_data.py sample_data/people.csv \
  --target-col is_active \
  --diagnostic-bundle-out tmp/diagnostic_bundle.json
```

After: turn that diagnostic bundle into model-family recommendations.

```bash
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle.json \
  --recommendation-out tmp/recommendation_bundle.json
```

Full feedback-loop smoke test:

```bash
python3 scripts/test_feedback_loop_e2e.py
```

## CLI Notes

Useful diagnostic hints:

- `--target-col`
- `--task-hint`
- `--time-col`
- `--group-col`
- `--split-col`
- `--id-cols`
- `--metric`

Useful outputs:

- `--assumptions-out tmp/assumptions.json`
- `--diagnostic-bundle-out tmp/diagnostic_bundle.json`
- `--strict-assumptions`
- `--no-diagnostics`

## Python API

The installable package exposes the inspection engine directly:

```python
from pathlib import Path

from data_inspector.core.context import InspectionContext
from data_inspector.core.engine import InspectionEngine

engine = InspectionEngine.default()
reports = engine.inspect_path(
    Path("sample_data/people.csv"),
    InspectionContext(target_column="is_active"),
)

print(reports[0].detection.file_type)
```

## Repository Layout

- `ingestor_island/src/data_inspector/`: installable inspection package and CLI.
- `model_selector_island/src/model_selector/`: heuristic model recommendation engine.
- `collator_island/`: probe execution and feedback-loop support code.
- `contracts/`: JSON schemas for diagnostic, recommendation, and probe bundles.
- `sample_data/`: small example datasets used for demos and smoke tests.
- `scripts/`: sample-data generation and end-to-end verification scripts.
- `OPERATOR_README.md`: runbook-oriented documentation.
- `ENGINEER_README.md`: architecture and implementation notes.

## Limitations

- Detection and diagnostics are heuristic by design and should not be treated as ground truth.
- Large files are sampled and summarized rather than exhaustively analyzed.
- The installable package is the inspection engine; the selector and collator remain repo-local companion tooling.
- Pickle files are detected but not unpickled unless you pass `--unsafe-unpickle`.

## Additional Docs

- [OPERATOR_README.md](OPERATOR_README.md)
- [ENGINEER_README.md](ENGINEER_README.md)
- [contracts/README.md](contracts/README.md)

## License

MIT. See [LICENSE](LICENSE).
