from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

DIAGNOSTIC_SCHEMA_VERSION = "diagnostic_bundle.v1"
RECOMMENDATION_SCHEMA_VERSION = "recommendation_bundle.v1"
PROBE_REQUEST_SCHEMA_VERSION = "probe_request_bundle.v1"
PROBE_RESULT_SCHEMA_VERSION = "probe_result_bundle.v1"
LOOP_DECISION_SCHEMA_VERSION = "loop_decision_bundle.v1"


def load_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path).expanduser()
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected top-level JSON object in {p}")
    return obj


def dump_json(path: str | Path, payload: Dict[str, Any]) -> Path:
    out = Path(path).expanduser()
    if out.exists() and out.is_dir():
        out = out / "recommendation_bundle.json"
    elif out.suffix.lower() != ".json":
        out.mkdir(parents=True, exist_ok=True)
        out = out / "recommendation_bundle.json"
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def stable_payload_hash(payload: Dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def validate_diagnostic_bundle(bundle: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if bundle.get("schema_version") != DIAGNOSTIC_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be '{DIAGNOSTIC_SCHEMA_VERSION}', got {bundle.get('schema_version')!r}"
        )

    for key in ("run_id", "generated_at_utc", "producer", "input", "summary", "datasets"):
        if key not in bundle:
            errors.append(f"Missing required key: {key}")

    datasets = bundle.get("datasets")
    if not isinstance(datasets, list):
        errors.append("datasets must be a list")
        return errors

    for idx, ds in enumerate(datasets):
        if not isinstance(ds, dict):
            errors.append(f"datasets[{idx}] must be an object")
            continue
        for key in ("dataset_id", "display_name", "detected_type", "coverage", "assumptions", "vital_findings"):
            if key not in ds:
                errors.append(f"datasets[{idx}] missing key: {key}")
        if ds.get("readiness_state") not in {"ready", "degraded", "blocked"}:
            errors.append(f"datasets[{idx}].readiness_state must be ready|degraded|blocked")

    return errors


def validate_recommendation_bundle(bundle: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if bundle.get("schema_version") != RECOMMENDATION_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be '{RECOMMENDATION_SCHEMA_VERSION}', got {bundle.get('schema_version')!r}"
        )

    for key in ("run_id", "generated_at_utc", "producer", "input_diagnostic_hash", "summary", "datasets"):
        if key not in bundle:
            errors.append(f"Missing required key: {key}")

    datasets = bundle.get("datasets")
    if not isinstance(datasets, list):
        errors.append("datasets must be a list")
        return errors

    for idx, ds in enumerate(datasets):
        if not isinstance(ds, dict):
            errors.append(f"datasets[{idx}] must be an object")
            continue
        for key in (
            "dataset_id",
            "display_name",
            "decision_state",
            "required_user_actions",
            "recommended_objective_metric",
            "recommended_validation_strategy",
            "confidence_score",
            "blocking_reasons",
            "candidates",
        ):
            if key not in ds:
                errors.append(f"datasets[{idx}] missing key: {key}")
        if ds.get("decision_state") not in {"ready", "degraded", "blocked"}:
            errors.append(f"datasets[{idx}].decision_state must be ready|degraded|blocked")

        candidates = ds.get("candidates", [])
        if not isinstance(candidates, list):
            errors.append(f"datasets[{idx}].candidates must be a list")
            continue
        for j, cand in enumerate(candidates):
            if not isinstance(cand, dict):
                errors.append(f"datasets[{idx}].candidates[{j}] must be an object")
                continue
            for key in (
                "candidate_id",
                "rank",
                "family",
                "fit_score",
                "confidence",
                "rationale",
                "collator_intent",
                "hpo_space",
                "risks",
            ):
                if key not in cand:
                    errors.append(f"datasets[{idx}].candidates[{j}] missing key: {key}")

    return errors


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
            errors.append(f"requests[{idx}] must be an object")
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
        if req.get("priority") not in {"high", "medium", "low"}:
            errors.append(f"requests[{idx}].priority must be high|medium|low")
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
    results = bundle.get("results")
    if not isinstance(results, list):
        errors.append("results must be a list")
        return errors
    for idx, res in enumerate(results):
        if not isinstance(res, dict):
            errors.append(f"results[{idx}] must be an object")
            continue
        for key in (
            "request_id",
            "dataset_id",
            "status",
            "probe_kind",
            "signals",
            "metrics",
            "confidence_gain",
            "trials_run",
            "runtime_minutes",
            "artifacts",
            "error",
        ):
            if key not in res:
                errors.append(f"results[{idx}] missing key: {key}")
        if res.get("status") not in {"success", "failed", "partial"}:
            errors.append(f"results[{idx}].status must be success|failed|partial")
    return errors


def validate_loop_decision_bundle(bundle: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if bundle.get("schema_version") != LOOP_DECISION_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be '{LOOP_DECISION_SCHEMA_VERSION}', got {bundle.get('schema_version')!r}"
        )
    for key in (
        "run_id",
        "loop_run_id",
        "round_index",
        "generated_at_utc",
        "producer",
        "decision",
        "summary",
    ):
        if key not in bundle:
            errors.append(f"Missing required key: {key}")
    decision = bundle.get("decision")
    if not isinstance(decision, dict):
        errors.append("decision must be an object")
        return errors
    if decision.get("action") not in {"request_probes", "finalize", "await_operator", "stop"}:
        errors.append("decision.action must be request_probes|finalize|await_operator|stop")
    return errors
