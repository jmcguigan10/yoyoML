from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .contracts import DIAGNOSTIC_SCHEMA_VERSION


def normalize_diagnostic_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    version = str(payload.get("schema_version", ""))
    if version == DIAGNOSTIC_SCHEMA_VERSION:
        return payload
    if _looks_like_legacy_assumptions_payload(payload):
        return _adapt_legacy_assumptions_payload(payload)
    raise ValueError(
        "Unsupported diagnostic input format. Expected diagnostic_bundle.v1 or legacy assumptions payload."
    )


def _looks_like_legacy_assumptions_payload(payload: Dict[str, Any]) -> bool:
    return (
        "files" in payload
        and isinstance(payload.get("files"), list)
        and "generated_at_utc" in payload
        and "input_path" in payload
    )


def _adapt_legacy_assumptions_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    datasets: List[Dict[str, Any]] = []
    verify_count = 0

    for i, f in enumerate(files):
        if not isinstance(f, dict):
            continue
        assumptions = _normalize_legacy_assumptions(f.get("assumptions"))
        verify_count += sum(
            1
            for a in assumptions
            if str(a.get("status")) in {"needs_user_verification", "unresolved"}
        )
        readiness, readiness_reasons = _legacy_readiness(assumptions)
        blocking = readiness_reasons if readiness == "blocked" else []
        datasets.append(
            {
                "dataset_id": f"ds_{i+1:03d}",
                "display_name": str(f.get("display_name", f"dataset_{i+1}")),
                "detected_type": str(f.get("detected_type", "unknown")),
                "detection_confidence": 0.0,
                "input_fingerprint": _path_fingerprint(str(f.get("display_name", ""))),
                "coverage": {"supported_vital_checks": 0, "total_vital_checks": 12},
                "dataset_profile": {},
                "vital_findings": [],
                "assumptions": assumptions,
                "warnings": [],
                "readiness_state": readiness,
                "blocking_reasons": blocking,
                "required_user_actions": _dedupe(_required_user_actions(assumptions) + readiness_reasons),
                "confidence_score": _legacy_confidence(assumptions),
            }
        )

    if any(d.get("readiness_state") == "blocked" for d in datasets):
        overall_state = "blocked"
    elif any(d.get("readiness_state") == "degraded" for d in datasets):
        overall_state = "degraded"
    else:
        overall_state = "ready"

    confidence = (
        round(sum(float(d.get("confidence_score", 0.0)) for d in datasets) / len(datasets), 3)
        if datasets
        else 0.0
    )

    input_path = str(payload.get("input_path", "."))
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "run_id": f"diag_legacy_{uuid.uuid4().hex[:10]}",
        "generated_at_utc": str(payload.get("generated_at_utc") or datetime.now(timezone.utc).isoformat()),
        "producer": {
            "name": "ingestor_island.legacy_adapter",
            "version": "0.1.0",
        },
        "input": {
            "path": input_path,
            "fingerprint": _path_fingerprint(input_path),
        },
        "summary": {
            "dataset_count": len(datasets),
            "assumptions_needing_verification": verify_count,
            "supported_vital_checks": 0,
            "total_vital_checks": 12 * len(datasets),
            "readiness_state": overall_state,
            "confidence_score": confidence,
        },
        "datasets": datasets,
    }


def _normalize_legacy_assumptions(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "unresolved"))
        if status not in {"auto_accept", "needs_user_verification", "unresolved"}:
            status = "unresolved"
        out.append(
            {
                "key": str(item.get("key", "")),
                "value": item.get("value"),
                "confidence": _safe_conf(item.get("confidence")),
                "status": status,
                "source": str(item.get("source", "legacy_assumptions")),
                "evidence": [str(x) for x in (item.get("evidence") or []) if isinstance(x, (str, int, float))],
                "risk_if_wrong": str(item.get("risk_if_wrong", "")),
            }
        )
    return out


def _legacy_readiness(assumptions: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    by_key = {str(a.get("key")): a for a in assumptions}
    blocking: List[str] = []
    degraded: List[str] = []
    for core in ("task_type", "target_column"):
        item = by_key.get(core)
        if not item:
            blocking.append(f"Missing core assumption: {core}.")
            continue
        status = str(item.get("status"))
        value = item.get("value")
        if status == "unresolved" or value is None or value == "":
            blocking.append(f"Core assumption '{core}' is {status}.")
        elif status == "needs_user_verification":
            degraded.append(f"Core assumption '{core}' needs user verification.")
    if blocking:
        return "blocked", blocking

    for opt in ("split_column", "time_column", "group_column", "objective_metric"):
        item = by_key.get(opt)
        if not item or str(item.get("status")) in {"needs_user_verification", "unresolved"}:
            degraded.append(f"Optional assumption '{opt}' requires user confirmation.")
    if degraded:
        return "degraded", degraded
    return "ready", []


def _legacy_confidence(assumptions: List[Dict[str, Any]]) -> float:
    if not assumptions:
        return 0.0
    vals = []
    for a in assumptions:
        conf = _safe_conf(a.get("confidence"))
        status = str(a.get("status"))
        if status == "auto_accept":
            vals.append(conf)
        elif status == "needs_user_verification":
            vals.append(conf * 0.6)
        else:
            vals.append(0.0)
    return round(sum(vals) / max(1, len(vals)), 3)


def _required_user_actions(assumptions: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for a in assumptions:
        status = str(a.get("status"))
        if status not in {"needs_user_verification", "unresolved"}:
            continue
        key = str(a.get("key"))
        if status == "needs_user_verification":
            out.append(f"Verify assumption '{key}' value.")
        else:
            out.append(f"Provide missing assumption '{key}'.")
    return out


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _path_fingerprint(raw_path: str) -> Dict[str, Any]:
    p = Path(raw_path).expanduser()
    if not p.exists():
        digest = hashlib.sha256(raw_path.encode("utf-8")).hexdigest()
        return {"kind": "missing", "path": str(p), "fingerprint_sha256": digest}
    st = p.stat()
    payload = f"{p}|{int(st.st_size)}|{int(st.st_mtime_ns)}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "kind": "path",
        "path": str(p),
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "fingerprint_sha256": digest,
    }


def _safe_conf(v: Any) -> float:
    try:
        x = float(v)
    except Exception:
        return 0.0
    return round(min(1.0, max(0.0, x)), 3)
