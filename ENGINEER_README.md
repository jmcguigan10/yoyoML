# Engineer README

This document is for engineers maintaining/extending the codebase.

It covers:
- architecture by island
- contract boundaries
- recommender heuristics and feedback loop logic
- collator probe adapter behavior
- extension points and constraints

---

## 1) Architecture Overview

Repository layout:
- `ingestor_island/src/data_inspector`: active ingestion implementation
- `src/data_inspector`: compatibility shim package for legacy imports/entry points
- `ingestor_island/`: ingestion island ownership boundary
- `model_selector_island/src/model_selector`: recommendation and loop planner runtime
- `collator_island/`: copied collator prototype architecture
- `contracts/`: inter-island JSON contracts/schemas

Core philosophy:
- each island is independently optimizable
- cross-island communication is JSON-contract based only
- loop orchestration is deterministic and reproducible through IDs/hashes

---

## 2) Contract Surface

### Implemented contracts
- `diagnostic_bundle.v1.schema.json`
- `recommendation_bundle.v1.schema.json`
- `probe_request_bundle.v1.schema.json`
- `probe_result_bundle.v1.schema.json`
- `loop_decision_bundle.v1.schema.json`

### Contract conventions
- top-level `schema_version` is mandatory
- snake_case keys
- explicit state enums (no free-text states)
- include producer metadata and payload hashes where applicable

### Validation behavior
- lightweight in-code validators live in:
  `model_selector_island/src/model_selector/contracts.py`
- hard schema validation (jsonschema) is not currently runtime-enforced
  to keep dependencies minimal; validators enforce required envelope shape.

---

## 3) Ingestor Side Changes

### New module
- `ingestor_island/src/data_inspector/exchange.py`

Responsibilities:
- normalize raw diagnostics into `diagnostic_bundle.v1`
- compute dataset and root fingerprints
- derive dataset readiness (`ready/degraded/blocked`)
- compute confidence scores
- aggregate required user actions

### CLI integration
- `ingestor_island/src/data_inspector/cli.py`
  - added `--diagnostic-bundle-out`
  - still supports legacy `--assumptions-out`

Readiness policy:
- blocked:
  - core assumptions missing/unresolved (`task_type`, `target_column`)
  - or vital findings `problem_type` / `target_definition` unsupported
- degraded:
  - optional assumptions unresolved or key optional findings missing
- ready:
  - neither of the above

Important nuance:
- `needs_user_verification` on core assumptions is degraded (not blocked).

---

## 4) Recommender Core

### Modules
- `model_selector_island/src/model_selector/cli.py`
- `model_selector_island/src/model_selector/adapter.py`
- `model_selector_island/src/model_selector/heuristics.py`
- `model_selector_island/src/model_selector/feedback.py`
- `model_selector_island/src/model_selector/contracts.py`

### Data path
1. Load input JSON.
2. Normalize:
   - accept native `diagnostic_bundle.v1`
   - or adapt legacy assumptions JSON via `adapter.py`.
3. Validate normalized diagnostic payload.
4. Build `recommendation_bundle.v1`.
5. Build `loop_decision_bundle.v1`.
6. Optionally emit `probe_request_bundle.v1` when decision action is `request_probes`.

### Heuristic recommendation behavior
Current candidate families are constrained to collator-supported set:
- `mlp`
- `cnn`
- `mtl`

Candidate generation in `heuristics.py`:
- always MLP baseline for tabular/vector assumptions
- MTL when task hints imply multi-output behavior
- CNN probe only for high-dimensional NPZ vectors (image-like hypothesis)

Each candidate includes:
- `collator_intent` (pipeline/config fragment with unresolved fields explicit)
- bounded `hpo_space`
- rationale and risks

---

## 5) Feedback Loop State Machine

Implemented in:
- `model_selector_island/src/model_selector/feedback.py`

### Inputs
- `diagnostic_bundle.v1`
- `recommendation_bundle.v1`
- optional `probe_result_bundle.v1`
- loop parameters:
  - `round_index`
  - `max_rounds`
  - `max_total_probes`
  - `min_confidence_gain`

### Output actions
- `request_probes`
- `finalize`
- `await_operator`
- `stop`

### Decision logic (current)
1. `finalize` if all datasets are ready.
2. `stop` if round budget exceeded.
3. `stop` if probe result count exceeds total probe budget.
4. `await_operator` if only degraded remain and mean confidence gain from probes is below threshold.
5. `request_probes` if blocked/degraded remain.

### Probe request planning
Planner emits targeted probes per dataset (bounded by `max_probes_per_dataset`):
- `supervised_baseline_probe`
- `split_sensitivity_probe`
- `unsupervised_structure_probe`
- `missingness_impact_probe` (when relevant)

Probe dedupe:
- request IDs are deterministic UUIDv5 hashes derived from `(dataset_id, probe_kind, reason)`
- previously completed request IDs from `probe_result_bundle` are skipped

---

## 6) Collator Probe Adapter

Implemented in:
- `collator_island/mmtool/probe_runner.py`
- CLI wrapper: `collator_island/run_collator_probes.py`

Purpose:
- consume `probe_request_bundle.v1`
- emit `probe_result_bundle.v1`
- provide deterministic simulation metrics and confidence gains for loop integration

Behavior:
- supports candidate families: `mlp`, `cnn`, `mtl`
- unsupported families return `failed` results with explicit error
- metrics are deterministic functions of `request_id` and `probe_kind`
- runtime/trials are bounded by request budget

This adapter is deliberately simulation-based and contract-first. It is the integration seam before wiring full collator/HPO execution internals.

---

## 7) CLI Interface (Model Selector)

Baseline:
```bash
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle.json \
  --recommendation-out tmp/recommendation_bundle.json
```

Loop-enabled:
```bash
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle.json \
  --probe-result-in tmp/probe_result.round1.json \
  --recommendation-out tmp/recommendation_bundle.round2.json \
  --loop-decision-out tmp/loop_decision.round2.json \
  --probe-request-out tmp/probe_request.round2.json \
  --loop-run-id demo_loop \
  --round-index 2 \
  --max-rounds 3 \
  --max-total-probes 12 \
  --max-probes-per-dataset 2 \
  --min-confidence-gain 0.02
```

Behavior:
- `probe_request_out` is written only when action is `request_probes`
- otherwise CLI logs that probe request was not emitted

---

## 8) Testing

### End-to-end loop test

Script:
- `scripts/test_feedback_loop_e2e.py`

Run:
```bash
python3 scripts/test_feedback_loop_e2e.py
```

Test sequence:
1. regenerate sample data (`scripts/generate_test_data.py`)
2. run ingestor on `sample_data/people.csv`
3. run recommender round 1 and emit probe requests
4. run collator probe adapter to emit probe results
5. run recommender round 2 with probe feedback
6. assert expected contract schemas and loop state transition

Artifacts:
- `tmp/e2e_feedback_loop/*`

### Unit-level compile checks

Use:
```bash
python3 -m compileall ingestor_island/src/data_inspector model_selector_island/src/model_selector collator_island/mmtool
```

---

## 9) Extension Points

### A) Strengthen collator capability coupling
Current recommendation family constraints are static constants.
Upgrade path:
- ingest live collator manifest (for example from `collator_island/mmtool manifest`)
- dynamically constrain candidates/hpo knobs.

### B) Better probe-aware re-ranking
Current loop uses aggregate confidence gain from `probe_result_bundle`.
Upgrade path:
- per-dataset Bayesian updates
- per-candidate posterior score updates using probe metrics.

### C) Hard schema validation
Current validators are structural and lightweight.
Upgrade path:
- add `jsonschema` dependency
- validate every emitted artifact against schema files in `contracts/`.

### D) Add contract migrations
When introducing v2 schemas:
- add adapters `v1 -> v2`
- ensure backward read compatibility in CLI.

---

## 10) Operational Guarantees and Non-Guarantees

Guaranteed:
- deterministic envelope structure
- explicit state/action typing
- no hidden coupling between islands beyond JSON artifacts

Not guaranteed:
- global optimal model architecture (heuristic only)
- perfect task/target inference from ambiguous data
- hard security guarantees for untrusted JSON payloads

---

## 11) Developer Notes

- This repo is not currently a git repo in this workspace snapshot.
- Some sandbox policies may block destructive commands (`rm -rf`) during tool execution.
- Keep edits ASCII unless file already requires Unicode.

---

## 12) Quick Code Map

Ingestor:
- bundle builder: `ingestor_island/src/data_inspector/exchange.py`
- CLI: `ingestor_island/src/data_inspector/cli.py`

Recommender:
- CLI: `model_selector_island/src/model_selector/cli.py`
- contracts/helpers: `model_selector_island/src/model_selector/contracts.py`
- legacy adapter: `model_selector_island/src/model_selector/adapter.py`
- recommendation heuristics: `model_selector_island/src/model_selector/heuristics.py`
- feedback loop planner/state machine: `model_selector_island/src/model_selector/feedback.py`

Contracts:
- `contracts/*.schema.json`

Collator probe adapter:
- core: `collator_island/mmtool/probe_runner.py`
- CLI wrapper: `collator_island/run_collator_probes.py`
