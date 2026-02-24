from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from .contracts import stable_payload_hash

PROBE_REQUEST_SCHEMA_VERSION = "probe_request_bundle.v1"
PROBE_RESULT_SCHEMA_VERSION = "probe_result_bundle.v1"
LOOP_DECISION_SCHEMA_VERSION = "loop_decision_bundle.v1"
PRODUCER_NAME = "model_selector_island.feedback_loop"
PRODUCER_VERSION = "0.1.0"


def build_loop_decision_bundle(
    diagnostic_bundle: Dict[str, Any],
    recommendation_bundle: Dict[str, Any],
    *,
    probe_result_bundle: Dict[str, Any] | None = None,
    loop_run_id: str | None = None,
    round_index: int = 1,
    max_rounds: int = 3,
    max_total_probes: int = 12,
    min_confidence_gain: float = 0.02,
) -> Dict[str, Any]:
    loop_id = loop_run_id or f"loop_{uuid.uuid4().hex[:12]}"
    action, reason, should_emit = _decide_action(
        recommendation_bundle=recommendation_bundle,
        probe_result_bundle=probe_result_bundle,
        round_index=round_index,
        max_rounds=max_rounds,
        max_total_probes=max_total_probes,
        min_confidence_gain=min_confidence_gain,
    )

    rec_summary = recommendation_bundle.get("summary", {}) if isinstance(recommendation_bundle.get("summary"), dict) else {}
    probe_results = _probe_results_list(probe_result_bundle)
    mean_gain = _mean_confidence_gain(probe_results)

    return {
        "schema_version": LOOP_DECISION_SCHEMA_VERSION,
        "run_id": f"loop_dec_{uuid.uuid4().hex[:12]}",
        "loop_run_id": loop_id,
        "round_index": int(max(1, round_index)),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "producer": {
            "name": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
        },
        "decision": {
            "action": action,
            "reason": reason,
            "should_emit_probe_requests": should_emit,
        },
        "summary": {
            "dataset_count": _safe_int(rec_summary.get("dataset_count"), 0),
            "ready_count": _safe_int(rec_summary.get("ready_count"), 0),
            "degraded_count": _safe_int(rec_summary.get("degraded_count"), 0),
            "blocked_count": _safe_int(rec_summary.get("blocked_count"), 0),
            "probe_results_seen": len(probe_results),
            "mean_confidence_gain": round(mean_gain, 6),
        },
    }


def build_probe_request_bundle(
    diagnostic_bundle: Dict[str, Any],
    recommendation_bundle: Dict[str, Any],
    *,
    probe_result_bundle: Dict[str, Any] | None = None,
    loop_run_id: str | None = None,
    round_index: int = 1,
    max_rounds: int = 3,
    max_total_probes: int = 12,
    min_confidence_gain: float = 0.02,
    max_probes_per_dataset: int = 2,
) -> Dict[str, Any]:
    loop_id = loop_run_id or f"loop_{uuid.uuid4().hex[:12]}"
    datasets = recommendation_bundle.get("datasets", [])
    if not isinstance(datasets, list):
        datasets = []

    previous_ids = _previous_probe_ids(probe_result_bundle)
    requests: List[Dict[str, Any]] = []
    priority_counts = {"high": 0, "medium": 0, "low": 0}
    max_trials_total = 0
    max_runtime_total = 0

    for ds in datasets:
        if not isinstance(ds, dict):
            continue
        decision_state = str(ds.get("decision_state", "blocked"))
        if decision_state == "ready":
            continue

        dataset_id = str(ds.get("dataset_id", "unknown_dataset"))
        per_dataset = _plan_dataset_probes(
            dataset_id=dataset_id,
            dataset_recommendation=ds,
            max_count=max(1, max_probes_per_dataset),
        )

        for req in per_dataset:
            request_key = f"{dataset_id}:{req['probe_kind']}:{req['reason']}"
            req["request_id"] = f"probe_{uuid.uuid5(uuid.NAMESPACE_URL, request_key).hex[:16]}"
            if req["request_id"] in previous_ids:
                continue
            requests.append(req)
            prio = str(req.get("priority", "medium"))
            priority_counts[prio] = priority_counts.get(prio, 0) + 1
            budget = req.get("budget", {})
            max_trials_total += _safe_int((budget or {}).get("max_trials"), 0)
            max_runtime_total += _safe_int((budget or {}).get("max_runtime_minutes"), 0)

    # Bound by global budget cap.
    if len(requests) > max_total_probes:
        requests = requests[:max_total_probes]

    return {
        "schema_version": PROBE_REQUEST_SCHEMA_VERSION,
        "run_id": f"probe_req_{uuid.uuid4().hex[:12]}",
        "loop_run_id": loop_id,
        "round_index": int(max(1, round_index)),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "producer": {
            "name": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
        },
        "source_hashes": {
            "diagnostic_bundle_hash": stable_payload_hash(diagnostic_bundle),
            "recommendation_bundle_hash": stable_payload_hash(recommendation_bundle),
            "prior_probe_result_hash": stable_payload_hash(probe_result_bundle) if isinstance(probe_result_bundle, dict) else None,
        },
        "summary": {
            "request_count": len(requests),
            "dataset_count": len({str(r.get("dataset_id")) for r in requests}),
            "priority_counts": priority_counts,
            "estimated_budget": {
                "max_trials_total": int(max_trials_total),
                "max_runtime_minutes": int(max_runtime_total),
            },
        },
        "stop_conditions": {
            "max_rounds": int(max(1, max_rounds)),
            "max_total_probes": int(max(1, max_total_probes)),
            "min_confidence_gain": float(min_confidence_gain),
        },
        "requests": requests,
    }


def _decide_action(
    *,
    recommendation_bundle: Dict[str, Any],
    probe_result_bundle: Dict[str, Any] | None,
    round_index: int,
    max_rounds: int,
    max_total_probes: int,
    min_confidence_gain: float,
) -> Tuple[str, str, bool]:
    summary = recommendation_bundle.get("summary", {}) if isinstance(recommendation_bundle.get("summary"), dict) else {}
    dataset_count = _safe_int(summary.get("dataset_count"), 0)
    blocked_count = _safe_int(summary.get("blocked_count"), 0)
    degraded_count = _safe_int(summary.get("degraded_count"), 0)
    ready_count = _safe_int(summary.get("ready_count"), 0)

    probe_results = _probe_results_list(probe_result_bundle)
    total_results = len(probe_results)
    mean_gain = _mean_confidence_gain(probe_results)

    if dataset_count > 0 and ready_count == dataset_count and blocked_count == 0 and degraded_count == 0:
        return "finalize", "All datasets are ready with no blocked/degraded states.", False

    if round_index > max_rounds:
        return "stop", f"Round limit reached: round_index={round_index}, max_rounds={max_rounds}.", False

    if total_results >= max_total_probes:
        return "stop", f"Probe budget exhausted: {total_results} results >= max_total_probes={max_total_probes}.", False

    if total_results > 0 and blocked_count == 0 and degraded_count > 0 and mean_gain < float(min_confidence_gain):
        return (
            "await_operator",
            f"Confidence gain ({mean_gain:.4f}) is below threshold ({float(min_confidence_gain):.4f}) with degraded datasets remaining.",
            False,
        )

    if blocked_count > 0 or degraded_count > 0:
        return "request_probes", "Blocked/degraded datasets remain; targeted probes requested.", True

    return "finalize", "No additional probes required.", False


def _plan_dataset_probes(
    *,
    dataset_id: str,
    dataset_recommendation: Dict[str, Any],
    max_count: int,
) -> List[Dict[str, Any]]:
    candidates = dataset_recommendation.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    best = candidates[0] if candidates else None

    required_actions = [
        str(x)
        for x in (dataset_recommendation.get("required_user_actions") or [])
        if isinstance(x, str)
    ]
    probe_specs: List[Dict[str, Any]] = []

    # 1) Always request a supervised baseline probe if we have a candidate.
    if isinstance(best, dict):
        probe_specs.append(
            {
                "dataset_id": dataset_id,
                "priority": "high",
                "reason": "Need baseline performance to calibrate recommendation confidence.",
                "probe_kind": "supervised_baseline_probe",
                "expected_signals": [
                    "baseline_metric",
                    "overfit_gap",
                    "training_stability"
                ],
                "collator_request": {
                    "candidate_family": str(best.get("family", "mlp")),
                    "intent": best.get("collator_intent", {}),
                    "hpo": {
                        "sampler": ((best.get("hpo_space") or {}).get("sampler") or "tpe"),
                        "pruner": ((best.get("hpo_space") or {}).get("pruner") or "median"),
                        "max_trials": min(20, _safe_int(((best.get("hpo_space") or {}).get("max_trials")), 20))
                    }
                },
                "budget": {"max_trials": 20, "max_runtime_minutes": 30},
            }
        )

    # 2) Split-related uncertainty probe.
    if any("split" in act.lower() or "time" in act.lower() or "group" in act.lower() for act in required_actions):
        probe_specs.append(
            {
                "dataset_id": dataset_id,
                "priority": "medium",
                "reason": "Split/time/group uncertainty detected; run split sensitivity diagnostics.",
                "probe_kind": "split_sensitivity_probe",
                "expected_signals": [
                    "metric_variance_across_split_strategies",
                    "leakage_suspect_signal"
                ],
                "collator_request": {
                    "candidate_family": str((best or {}).get("family", "mlp")),
                    "intent": {
                        "mode": "cross_validation_probe",
                        "strategies": ["kfold", "stratified_kfold", "group_kfold", "time_series_split"]
                    },
                    "hpo": {"max_trials": 8}
                },
                "budget": {"max_trials": 8, "max_runtime_minutes": 25},
            }
        )

    # 3) Target uncertainty or missing target: unsupervised structure probe.
    if any("target" in act.lower() for act in required_actions) or not isinstance(best, dict):
        probe_specs.append(
            {
                "dataset_id": dataset_id,
                "priority": "high",
                "reason": "Target uncertainty remains; run unsupervised structure probe for separability/anomaly signals.",
                "probe_kind": "unsupervised_structure_probe",
                "expected_signals": [
                    "cluster_separation_score",
                    "reconstruction_error_profile",
                    "outlier_fraction"
                ],
                "collator_request": {
                    "candidate_family": "mlp",
                    "intent": {
                        "mode": "unsupervised_probe",
                        "algorithms": ["pca", "kmeans", "isolation_forest"]
                    },
                    "hpo": {"max_trials": 6}
                },
                "budget": {"max_trials": 6, "max_runtime_minutes": 20},
            }
        )

    # 4) Optional missingness probe.
    if any("missing" in act.lower() for act in required_actions):
        probe_specs.append(
            {
                "dataset_id": dataset_id,
                "priority": "low",
                "reason": "Missingness-related uncertainty detected; evaluate imputation robustness.",
                "probe_kind": "missingness_impact_probe",
                "expected_signals": [
                    "imputation_strategy_delta",
                    "missing_indicator_gain"
                ],
                "collator_request": {
                    "candidate_family": str((best or {}).get("family", "mlp")),
                    "intent": {
                        "mode": "ablation_probe",
                        "imputation_strategies": ["median", "most_frequent", "none_with_indicator"]
                    },
                    "hpo": {"max_trials": 6}
                },
                "budget": {"max_trials": 6, "max_runtime_minutes": 20},
            }
        )

    return probe_specs[: max(1, max_count)]


def _probe_results_list(probe_result_bundle: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not isinstance(probe_result_bundle, dict):
        return []
    results = probe_result_bundle.get("results", [])
    if not isinstance(results, list):
        return []
    return [r for r in results if isinstance(r, dict)]


def _mean_confidence_gain(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0
    vals = []
    for r in results:
        try:
            vals.append(float(r.get("confidence_gain", 0.0)))
        except Exception:
            continue
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def _previous_probe_ids(probe_result_bundle: Dict[str, Any] | None) -> set[str]:
    out: set[str] = set()
    for r in _probe_results_list(probe_result_bundle):
        req_id = r.get("request_id")
        if isinstance(req_id, str) and req_id:
            out.add(req_id)
    return out


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default
