# model_selector_island

Model recommendation heuristic engine.

## Role
- consume diagnostic JSON produced by the ingestor island
- normalize legacy assumptions JSON when needed
- emit ranked architecture recommendations for the collator/HPO flow

## Entry points
- root wrapper: `python3 recommend_models.py --diagnostic-in tmp/diagnostic_bundle.json --recommendation-out tmp/recommendation_bundle.json`
- module: `python3 -m model_selector.cli --diagnostic-in tmp/diagnostic_bundle.json --recommendation-out tmp/recommendation_bundle.json`

## IO contracts
- input: `contracts/diagnostic_bundle.v1.schema.json`
- output: `contracts/recommendation_bundle.v1.schema.json`
- feedback outputs:
  - `contracts/loop_decision_bundle.v1.schema.json`
  - `contracts/probe_request_bundle.v1.schema.json`
- feedback input:
  - `contracts/probe_result_bundle.v1.schema.json`

The recommender accepts legacy `assumptions.json` and auto-adapts it into `diagnostic_bundle.v1` before ranking candidates.

## Feedback loop CLI example

```bash
python3 recommend_models.py \
  --diagnostic-in tmp/diagnostic_bundle.json \
  --recommendation-out tmp/recommendation_bundle.round1.json \
  --loop-decision-out tmp/loop_decision.round1.json \
  --probe-request-out tmp/probe_request.round1.json \
  --loop-run-id demo_loop \
  --round-index 1
```

Then execute requested probes with the collator adapter:

```bash
python3 collator_island/run_collator_probes.py \
  --probe-request-in tmp/probe_request.round1.json \
  --probe-result-out tmp/probe_result.round1.json
```
