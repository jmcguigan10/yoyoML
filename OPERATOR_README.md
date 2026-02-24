# Operator README

This guide is for people operating the system, not modifying internals.

Use this for:
- running ingestion diagnostics
- generating model recommendations
- driving the recommender <-> collator/HPO feedback loop via JSON artifacts

---

## 1) What You Run

There are three islands:
- `ingestor_island` (runtime code in `ingestor_island/src/data_inspector`)
- `model_selector_island`
- `collator_island` (plus HPO runtime downstream)

Primary operator wrappers:
- `inspect_data.py` (ingestor)
- `recommend_models.py` (recommender + loop planning)

Contracts live in:
- `contracts/`

Artifacts convention:
- write generated bundles to `tmp/` (repo-local artifact directory)

---

## 2) Required JSON Artifacts

### From ingestor
- `diagnostic_bundle.v1`
  Schema: `contracts/diagnostic_bundle.v1.schema.json`

### From recommender
- `recommendation_bundle.v1`
  Schema: `contracts/recommendation_bundle.v1.schema.json`

### For feedback loop
- `loop_decision_bundle.v1`
  Schema: `contracts/loop_decision_bundle.v1.schema.json`
- `probe_request_bundle.v1` (recommender -> collator/HPO)
  Schema: `contracts/probe_request_bundle.v1.schema.json`
- `probe_result_bundle.v1` (collator/HPO -> recommender)
  Schema: `contracts/probe_result_bundle.v1.schema.json`

---

## 3) Standard Workflow (No Feedback Yet)

### Step A: Run ingestion diagnostics

```bash
python3 inspect_data.py sample_data/people.csv \
  --diagnostic-bundle-out tmp/diagnostic_bundle.json \
  --assumptions-out tmp/assumptions.json
```

Notes:
- `--assumptions-out` is legacy-compatible and still useful for quick review.
- `--diagnostic-bundle-out` is the primary input for recommender and loop.

### Step B: Generate recommendations

```bash
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle.json \
  --recommendation-out tmp/recommendation_bundle.json
```

Outputs:
- `tmp/recommendation_bundle.json`

---

## 4) Feedback Loop Workflow

### Step 1: Initial recommendation + loop decision + probe requests

```bash
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle.json \
  --recommendation-out tmp/recommendation_bundle.round1.json \
  --loop-decision-out tmp/loop_decision.round1.json \
  --probe-request-out tmp/probe_request.round1.json \
  --loop-run-id run_2026_02_23_a \
  --round-index 1
```

Interpret:
- If decision action is `request_probes`, send `probe_request.round1.json` to collator/HPO.
- If decision action is `finalize`, use recommendations directly.
- If decision action is `await_operator`, gather additional human hints.
- If decision action is `stop`, terminate probing for this loop run.

### Step 2: Collator/HPO executes probes

Collator/HPO should consume `probe_request_bundle.v1` and emit:
- `probe_result_bundle.v1`

Required by recommender:
- `loop_run_id`
- `round_index`
- `results[]` with `confidence_gain`, `status`, and metrics

Current adapter command:

```bash
python3 collator_island/run_collator_probes.py \
  --probe-request-in tmp/probe_request.round1.json \
  --probe-result-out tmp/probe_result.round1.json
```

### Step 3: Next round with probe feedback

```bash
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle.json \
  --probe-result-in tmp/probe_result.round1.json \
  --recommendation-out tmp/recommendation_bundle.round2.json \
  --loop-decision-out tmp/loop_decision.round2.json \
  --probe-request-out tmp/probe_request.round2.json \
  --loop-run-id run_2026_02_23_a \
  --round-index 2
```

Repeat until:
- loop decision says `finalize`, or
- loop decision says `stop`, or
- operator stops loop manually.

---

## 5) Operator Control Knobs

`recommend_models.py` loop knobs:
- `--max-rounds` (default `3`)
- `--max-total-probes` (default `12`)
- `--max-probes-per-dataset` (default `2`)
- `--min-confidence-gain` (default `0.02`)

Meaning:
- If rounds exceed `max-rounds`, action becomes `stop`.
- If probe results count exceeds `max-total-probes`, action becomes `stop`.
- If only degraded datasets remain and mean confidence gain < threshold, action becomes `await_operator`.

---

## 6) Decision States and Actions

Dataset-level recommendation states:
- `ready`: recommendation can run now
- `degraded`: recommendation is usable but assumptions/coverage remain uncertain
- `blocked`: core uncertainty unresolved (for example missing task/target)

Loop actions:
- `request_probes`: generate targeted probe requests for collator/HPO
- `finalize`: stop probing, consume recommendations
- `await_operator`: ask human/operator for disambiguation
- `stop`: budget/round limits reached

---

## 7) Expected File Naming Convention

Suggested naming:
- `diagnostic_bundle.<dataset>.json`
- `recommendation_bundle.<loop_run_id>.roundN.json`
- `loop_decision.<loop_run_id>.roundN.json`
- `probe_request.<loop_run_id>.roundN.json`
- `probe_result.<loop_run_id>.roundN.json`

Keep `loop_run_id` stable across rounds.

---

## 8) Troubleshooting

### “validation failed” from recommender
- Ensure input is `diagnostic_bundle.v1` or legacy assumptions JSON.
- Check required keys in schema under `contracts/`.

### No probe request emitted
- Look at loop decision action in `loop_decision_bundle`.
- `probe_request` is emitted only when action is `request_probes`.

### Too many required user actions
- Provide better hints during ingestion:
  - `--target-col`
  - `--task-hint`
  - `--split-col`
  - `--time-col`
  - `--group-col`
  - `--metric`

## 9) Full E2E test

Run the full generated-data loop test:

```bash
python3 scripts/test_feedback_loop_e2e.py
```

This test performs:
1. sample data generation
2. ingestor diagnostics bundle creation
3. recommender round 1 (`request_probes`)
4. collator probe adapter execution
5. recommender round 2 with probe feedback (`await_operator` under strict gain threshold)

Artifacts are written under `tmp/e2e_feedback_loop/`.

---

## 10) Minimal End-to-End Example

```bash
# 1) Inspect and generate diagnostic bundle.
python3 inspect_data.py sample_data/train_data_random.npz \
  --diagnostic-bundle-out tmp/diagnostic_bundle_npz.json

# 2) Generate recommendations and initial loop artifacts.
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle_npz.json \
  --recommendation-out tmp/recommendation_bundle_npz.round1.json \
  --loop-decision-out tmp/loop_decision_npz.round1.json \
  --probe-request-out tmp/probe_request_npz.round1.json \
  --loop-run-id npz_demo_loop \
  --round-index 1
```

At this point:
- send `probe_request_npz.round1.json` to collator/HPO (if action=`request_probes`)
- bring back `probe_result_npz.round1.json`
- run round 2 with `--probe-result-in`.
