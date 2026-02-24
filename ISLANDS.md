# Islands Layout

This repository is organized as independent source islands that communicate via JSON artifacts.

## 1) Data Ingestion / Diagnostics Island
- Island path: `ingestor_island`
- Current implementation path: `ingestor_island/src/data_inspector`
- Responsibility: file inspection, tabular profiling, vital diagnostics, assumptions output.
- Primary output artifacts: assumptions JSON and `diagnostic_bundle.v1` JSON.

## 2) Collator / Pipeline Assembly Island
- Path: `collator_island`
- Responsibility: capability-aware pipeline generation and assembly (prototype from `mm_protv2`).
- Includes: `mmtool/`, `txt_store/`, `examples/`, `browser_ui/`, `snippet_db/`.
- Feedback adapter artifact: emits `probe_result_bundle.v1` from `probe_request_bundle.v1`.

## 3) Model Selection Heuristics Island
- Path: `model_selector_island`
- Responsibility: consume diagnostics JSON + collator capabilities, rank/select model architecture candidates.
- Primary output artifact: `recommendation_bundle.v1` JSON.

## Shared JSON Contracts
- Path: `contracts`
- Purpose: versioned schemas/contracts used between islands.
