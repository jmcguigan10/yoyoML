from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROBE_REQUEST_SCHEMA_VERSION = "probe_request_bundle.v1"
PROBE_RESULT_SCHEMA_VERSION = "probe_result_bundle.v1"

SUPPORTED_FAMILIES = {"mlp", "cnn", "mtl"}


def load_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path).expanduser()
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected object JSON at {p}")
    return obj


def dump_json(path: str | Path, payload: Dict[str, Any]) -> Path:
    out = Path(path).expanduser()
    if out.exists() and out.is_dir():
        out = out / "probe_result_bundle.json"
    elif out.suffix.lower() != ".json":
        out.mkdir(parents=True, exist_ok=True)
        out = out / "probe_result_bundle.json"
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def stable_payload_hash(payload: Dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def validate_probe_request_bundle(bundle: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if bundle.get("schema_version") != PROBE_REQUEST_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be '{PROBE_REQUEST_SCHEMA_VERSION}', got {bundle.get('schema_version')!r}"
        )
    for key in (
        "run_id",
        "loop_run_id",
        "round_index",
        "generated_at_utc",
        "producer",
        "source_hashes",
        "summary",
        "requests",
        "stop_conditions",
    ):
        if key not in bundle:
            errors.append(f"Missing required key: {key}")
    requests = bundle.get("requests")
    if not isinstance(requests, list):
        errors.append("requests must be a list")
        return errors
    for idx, req in enumerate(requests):
        if not isinstance(req, dict):
            errors.append(f"requests[{idx}] must be object")
            continue
        for key in (
            "request_id",
            "dataset_id",
            "priority",
            "reason",
            "probe_kind",
            "expected_signals",
            "collator_request",
            "budget",
        ):
            if key not in req:
                errors.append(f"requests[{idx}] missing key: {key}")
    return errors


def validate_probe_result_bundle(bundle: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if bundle.get("schema_version") != PROBE_RESULT_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be '{PROBE_RESULT_SCHEMA_VERSION}', got {bundle.get('schema_version')!r}"
        )
    for key in (
        "run_id",
        "loop_run_id",
        "round_index",
        "generated_at_utc",
        "producer",
        "source_probe_request_hash",
        "summary",
        "results",
    ):
        if key not in bundle:
            errors.append(f"Missing required key: {key}")
    return errors


def run_probe_bundle(
    probe_request_bundle: Dict[str, Any],
    *,
    producer_name: str = "collator_island.probe_runner",
    producer_version: str = "0.1.0",
) -> Dict[str, Any]:
    requests = probe_request_bundle.get("requests", [])
    if not isinstance(requests, list):
        requests = []

    results: List[Dict[str, Any]] = []
    for req in requests:
        if not isinstance(req, dict):
            continue
        results.append(_execute_request(req))

    success = len([r for r in results if r.get("status") == "success"])
    failed = len([r for r in results if r.get("status") == "failed"])
    gains = [float(r.get("confidence_gain", 0.0)) for r in results if isinstance(r.get("confidence_gain"), (int, float))]
    mean_gain = (sum(gains) / len(gains)) if gains else 0.0
    trials = sum(_safe_int(r.get("trials_run"), 0) for r in results)

    return {
        "schema_version": PROBE_RESULT_SCHEMA_VERSION,
        "run_id": f"probe_res_{uuid.uuid4().hex[:12]}",
        "loop_run_id": str(probe_request_bundle.get("loop_run_id", "")),
        "round_index": _safe_int(probe_request_bundle.get("round_index"), 1),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "producer": {
            "name": producer_name,
            "version": producer_version,
        },
        "source_probe_request_hash": stable_payload_hash(probe_request_bundle),
        "summary": {
            "result_count": len(results),
            "success_count": success,
            "failed_count": failed,
            "mean_confidence_gain": round(mean_gain, 6),
            "total_trials_run": trials,
        },
        "results": results,
    }


def _execute_request(req: Dict[str, Any]) -> Dict[str, Any]:
    request_id = str(req.get("request_id", f"probe_req_{uuid.uuid4().hex[:8]}"))
    dataset_id = str(req.get("dataset_id", "unknown_dataset"))
    probe_kind = str(req.get("probe_kind", "uncertainty_resolution_probe"))
    expected_signals = req.get("expected_signals", [])
    if not isinstance(expected_signals, list):
        expected_signals = []

    collator_request = req.get("collator_request", {})
    if not isinstance(collator_request, dict):
        collator_request = {}
    family = str(collator_request.get("candidate_family", "mlp")).lower()
    budget = req.get("budget", {})
    if not isinstance(budget, dict):
        budget = {}
    max_trials = max(1, _safe_int(budget.get("max_trials"), 8))
    max_runtime_minutes = max(1, _safe_int(budget.get("max_runtime_minutes"), 10))

    seed = _deterministic_unit_interval(request_id)

    if family not in SUPPORTED_FAMILIES:
        return {
            "request_id": request_id,
            "dataset_id": dataset_id,
            "status": "failed",
            "probe_kind": probe_kind,
            "signals": [],
            "metrics": {},
            "confidence_gain": 0.0,
            "trials_run": 0,
            "runtime_minutes": 0.0,
            "artifacts": {
                "notes": "Unsupported candidate family for this collator prototype."
            },
            "error": f"Unsupported candidate family '{family}'. Supported: {sorted(SUPPORTED_FAMILIES)}",
        }

    metrics, confidence_gain = _simulate_probe_metrics(probe_kind, seed, max_trials)
    trials_run = max(1, int(round(max_trials * (0.7 + 0.25 * seed))))
    runtime_minutes = round(min(float(max_runtime_minutes), (trials_run * (0.35 + 0.15 * seed))), 3)

    signal_out = [str(s) for s in expected_signals] if expected_signals else _default_signals(probe_kind)
    signal_out = signal_out[:8]

    return {
        "request_id": request_id,
        "dataset_id": dataset_id,
        "status": "success",
        "probe_kind": probe_kind,
        "signals": signal_out,
        "metrics": metrics,
        "confidence_gain": round(confidence_gain, 6),
        "trials_run": trials_run,
        "runtime_minutes": runtime_minutes,
        "artifacts": {
            "collator_run_id": f"collator_run_{uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex[:12]}",
            "candidate_family": family,
            "summary_uri": f"mock://collator/{dataset_id}/{request_id}/summary.json",
        },
        "error": None,
    }


def _simulate_probe_metrics(probe_kind: str, seed: float, max_trials: int) -> Tuple[Dict[str, Any], float]:
    if probe_kind == "supervised_baseline_probe":
        val_metric = 0.58 + (0.22 * seed)
        train_metric = min(0.98, val_metric + 0.04 + (0.06 * seed))
        overfit_gap = max(0.0, train_metric - val_metric)
        gain = 0.02 + (0.04 * seed)
        return (
            {
                "val_metric": round(val_metric, 6),
                "train_metric": round(train_metric, 6),
                "overfit_gap": round(overfit_gap, 6),
                "max_trials_budget": max_trials,
            },
            gain,
        )

    if probe_kind == "split_sensitivity_probe":
        variance = 0.01 + (0.08 * (1.0 - seed))
        leakage_score = 0.02 + (0.25 * (1.0 - seed))
        gain = 0.018 + (0.03 * (1.0 - variance))
        return (
            {
                "metric_variance_across_splits": round(variance, 6),
                "leakage_suspect_score": round(leakage_score, 6),
            },
            gain,
        )

    if probe_kind == "unsupervised_structure_probe":
        silhouette = -0.02 + (0.42 * seed)
        outlier_fraction = 0.01 + (0.19 * (1.0 - seed))
        recon_error = 0.08 + (0.45 * (1.0 - seed))
        gain = 0.015 + (0.035 * abs(silhouette))
        return (
            {
                "silhouette_score": round(silhouette, 6),
                "outlier_fraction": round(outlier_fraction, 6),
                "reconstruction_error": round(recon_error, 6),
            },
            gain,
        )

    if probe_kind == "missingness_impact_probe":
        delta = -0.03 + (0.12 * seed)
        indicator_gain = -0.02 + (0.09 * seed)
        gain = 0.01 + (0.03 * abs(delta))
        return (
            {
                "imputation_strategy_delta": round(delta, 6),
                "missing_indicator_gain": round(indicator_gain, 6),
            },
            gain,
        )

    if probe_kind == "feature_redundancy_probe":
        kept_ratio = 0.5 + (0.4 * seed)
        metric_delta = -0.05 + (0.08 * seed)
        gain = 0.008 + (0.03 * abs(metric_delta))
        return (
            {
                "kept_feature_ratio": round(kept_ratio, 6),
                "metric_delta_after_pruning": round(metric_delta, 6),
            },
            gain,
        )

    # uncertainty_resolution_probe and default fallback.
    gain = 0.01 + (0.03 * seed)
    return (
        {
            "probe_strength": round(0.4 + (0.5 * seed), 6),
            "consistency_score": round(0.5 + (0.4 * seed), 6),
        },
        gain,
    )


def _default_signals(probe_kind: str) -> List[str]:
    mapping = {
        "supervised_baseline_probe": ["baseline_metric", "overfit_gap", "training_stability"],
        "split_sensitivity_probe": ["metric_variance_across_split_strategies", "leakage_suspect_signal"],
        "unsupervised_structure_probe": ["cluster_separation_score", "outlier_fraction"],
        "missingness_impact_probe": ["imputation_strategy_delta", "missing_indicator_gain"],
        "feature_redundancy_probe": ["kept_feature_ratio", "metric_delta_after_pruning"],
        "uncertainty_resolution_probe": ["probe_strength", "consistency_score"],
    }
    return mapping.get(probe_kind, ["probe_strength", "consistency_score"])


def _deterministic_unit_interval(text: str) -> float:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    n = int(h[:12], 16)
    return n / float(16**12 - 1)


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default
