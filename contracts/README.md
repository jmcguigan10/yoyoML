# Contracts

Versioned JSON contracts for inter-island communication.

## Files
- `diagnostic_bundle.v1.schema.json`
  Ingestor output and recommender input.
- `recommendation_bundle.v1.schema.json`
  Recommender output and collator/HPO input.
- `probe_request_bundle.v1.schema.json`
  Recommender loop planner output to collator/HPO for targeted probe execution.
- `probe_result_bundle.v1.schema.json`
  Collator/HPO probe execution feedback to recommender.
- `loop_decision_bundle.v1.schema.json`
  Recommender loop controller decision output (`request_probes|finalize|await_operator|stop`).

## Notes
- `schema_version` is required in every payload.
- Contracts are intentionally strict for envelope fields and flexible in nested evidence payloads.
- Producers should emit deterministic key names (`snake_case`) and explicit status enums.

## Feedback Loop Flow
1. Ingestor emits `diagnostic_bundle.v1`.
2. Recommender emits `recommendation_bundle.v1` and `loop_decision_bundle.v1`.
3. If loop decision action is `request_probes`, recommender emits `probe_request_bundle.v1`.
4. Collator/HPO executes probes and emits `probe_result_bundle.v1`.
  Development adapter command:
  `python3 collator_island/run_collator_probes.py --probe-request-in tmp/probe_request.round1.json --probe-result-out tmp/probe_result.round1.json`
5. Recommender consumes probe results and repeats the decision cycle.
