from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .core.report import InspectionReport

SCHEMA_VERSION = "diagnostic_bundle.v1"
PRODUCER_NAME = "ingestor_island.data_inspector"
PRODUCER_VERSION = "0.1.0"

CORE_ASSUMPTIONS = {"task_type", "target_column"}
OPTIONAL_ASSUMPTIONS = {"split_column", "time_column", "group_column", "objective_metric"}


def build_diagnostic_bundle(
    reports: Iterable[InspectionReport],
    input_path: Path,
) -> Dict[str, Any]:
    report_list = list(reports)
    datasets: List[Dict[str, Any]] = []

    verify_count = 0
    supported_total = 0
    vital_total = 0
    state_counts = {"ready": 0, "degraded": 0, "blocked": 0}

    for idx, report in enumerate(report_list):
        diagnostics = report.diagnostics if isinstance(report.diagnostics, dict) else {}
        coverage = diagnostics.get("coverage", {}) if isinstance(diagnostics, dict) else {}
        findings = _normalize_findings(diagnostics.get("findings", []))
        assumptions = _normalize_assumptions(diagnostics.get("assumptions", []))
        profile = diagnostics.get("profile", {}) if isinstance(diagnostics.get("profile", {}), dict) else {}

        supported = int(_safe_int(coverage.get("supported_vital_checks"), 0))
        total = int(_safe_int(coverage.get("total_vital_checks"), 12))
        if total <= 0:
            total = 12

        supported_total += supported
        vital_total += total
        verify_count += sum(
            1
            for a in assumptions
            if str(a.get("status")) in {"needs_user_verification", "unresolved"}
        )

        dataset_path = Path(str(report.display_name)).expanduser()
        dataset_state, readiness_reasons = _dataset_readiness_state(assumptions, findings)
        state_counts[dataset_state] = state_counts.get(dataset_state, 0) + 1

        confidence = _dataset_confidence_score(supported, total, assumptions, findings)
        required_actions = _dedupe(_required_user_actions(assumptions) + readiness_reasons)
        blocking_reasons = readiness_reasons if dataset_state == "blocked" else []

        datasets.append(
            {
                "dataset_id": f"ds_{idx+1:03d}",
                "display_name": str(report.display_name),
                "detected_type": str(getattr(report.detection, "file_type", "unknown")),
                "detection_confidence": float(getattr(report.detection, "confidence", 0.0) or 0.0),
                "input_fingerprint": _fingerprint_path(dataset_path),
                "coverage": {
                    "supported_vital_checks": supported,
                    "total_vital_checks": total,
                },
                "dataset_profile": profile,
                "vital_findings": findings,
                "assumptions": assumptions,
                "warnings": [str(w) for w in (report.warnings or [])],
                "readiness_state": dataset_state,
                "blocking_reasons": blocking_reasons,
                "required_user_actions": required_actions,
                "confidence_score": confidence,
            }
        )

    if state_counts.get("blocked", 0) > 0:
        overall_state = "blocked"
    elif state_counts.get("degraded", 0) > 0:
        overall_state = "degraded"
    else:
        overall_state = "ready"

    confidence_values = [float(d.get("confidence_score", 0.0)) for d in datasets]
    overall_confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"diag_{uuid.uuid4().hex[:12]}",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "producer": {
            "name": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
        },
        "input": {
            "path": str(input_path),
            "fingerprint": _fingerprint_path(input_path),
        },
        "summary": {
            "dataset_count": len(datasets),
            "assumptions_needing_verification": verify_count,
            "supported_vital_checks": supported_total,
            "total_vital_checks": vital_total,
            "readiness_state": overall_state,
            "confidence_score": overall_confidence,
        },
        "datasets": datasets,
    }


def _normalize_findings(raw_findings: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_findings, list):
        return []
    out: List[Dict[str, Any]] = []
    for f in raw_findings:
        if not isinstance(f, dict):
            continue
        out.append(
            {
                "key": str(f.get("key", "")),
                "title": str(f.get("title", "")),
                "status": _safe_status(str(f.get("status", "needs_input"))),
                "confidence": _safe_float(f.get("confidence"), 0.0),
                "summary": str(f.get("summary", "")),
                "evidence": f.get("evidence", {}) if isinstance(f.get("evidence"), dict) else {},
                "warnings": [str(x) for x in (f.get("warnings") or []) if isinstance(x, (str, int, float))],
            }
        )
    return out


def _normalize_assumptions(raw_assumptions: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_assumptions, list):
        return []
    out: List[Dict[str, Any]] = []
    for a in raw_assumptions:
        if not isinstance(a, dict):
            continue
        status = str(a.get("status", "unresolved"))
        if status not in {"auto_accept", "needs_user_verification", "unresolved"}:
            status = "unresolved"
        out.append(
            {
                "key": str(a.get("key", "")),
                "value": a.get("value"),
                "confidence": _safe_float(a.get("confidence"), 0.0),
                "status": status,
                "source": str(a.get("source", "")),
                "evidence": [str(x) for x in (a.get("evidence") or []) if isinstance(x, (str, int, float))],
                "risk_if_wrong": str(a.get("risk_if_wrong", "")),
            }
        )
    return out


def _dataset_readiness_state(
    assumptions: List[Dict[str, Any]],
    findings: List[Dict[str, Any]],
) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    degraded_reasons: List[str] = []
    by_key = {str(a.get("key")): a for a in assumptions}
    finding_by_key = {str(f.get("key")): f for f in findings}

    for key in sorted(CORE_ASSUMPTIONS):
        item = by_key.get(key)
        if not item:
            reasons.append(f"Missing core assumption: {key}.")
            continue
        status = str(item.get("status"))
        value = item.get("value")
        if status == "unresolved" or value is None or value == "":
            reasons.append(f"Core assumption '{key}' is {status}.")
        elif status == "needs_user_verification":
            degraded_reasons.append(f"Core assumption '{key}' needs user verification.")

    for vital_key in ("problem_type", "target_definition"):
        status = str((finding_by_key.get(vital_key) or {}).get("status", "needs_input"))
        if status != "supported":
            reasons.append(f"Vital diagnostic '{vital_key}' is not supported.")

    if reasons:
        return "blocked", reasons

    for key in sorted(OPTIONAL_ASSUMPTIONS):
        item = by_key.get(key)
        if not item:
            degraded_reasons.append(f"Optional assumption '{key}' missing.")
            continue
        status = str(item.get("status"))
        if status in {"needs_user_verification", "unresolved"}:
            degraded_reasons.append(f"Optional assumption '{key}' is {status}.")

    for vital_key in ("data_splitting_structure", "evaluation_metric"):
        status = str((finding_by_key.get(vital_key) or {}).get("status", "needs_input"))
        if status != "supported":
            degraded_reasons.append(f"Vital diagnostic '{vital_key}' needs more input.")

    if degraded_reasons:
        return "degraded", degraded_reasons
    return "ready", []


def _dataset_confidence_score(
    supported: int,
    total: int,
    assumptions: List[Dict[str, Any]],
    findings: List[Dict[str, Any]],
) -> float:
    coverage_ratio = float(supported / max(1, total))

    if assumptions:
        weighted = []
        for a in assumptions:
            conf = _safe_float(a.get("confidence"), 0.0)
            status = str(a.get("status"))
            if status == "auto_accept":
                weighted.append(conf)
            elif status == "needs_user_verification":
                weighted.append(conf * 0.6)
            else:
                weighted.append(0.0)
        assumption_score = sum(weighted) / max(1, len(weighted))
    else:
        assumption_score = 0.0

    finding_conf = (
        sum(_safe_float(f.get("confidence"), 0.0) for f in findings) / max(1, len(findings))
        if findings
        else 0.0
    )

    score = (0.50 * coverage_ratio) + (0.30 * assumption_score) + (0.20 * finding_conf)
    return round(max(0.0, min(1.0, score)), 3)


def _required_user_actions(assumptions: List[Dict[str, Any]]) -> List[str]:
    actions: List[str] = []
    for a in assumptions:
        status = str(a.get("status"))
        if status not in {"needs_user_verification", "unresolved"}:
            continue
        key = str(a.get("key"))
        value = a.get("value")
        if status == "needs_user_verification":
            actions.append(f"Verify assumption '{key}' (current value: {value!r}).")
        else:
            actions.append(f"Provide value for unresolved assumption '{key}'.")
    return actions


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _fingerprint_path(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"kind": "missing", "path": str(path)}
    if path.is_dir():
        file_count = 0
        total_size = 0
        newest_mtime_ns = 0
        for p in path.rglob("*"):
            if not p.is_file():
                continue
            file_count += 1
            st = p.stat()
            total_size += int(st.st_size)
            newest_mtime_ns = max(newest_mtime_ns, int(st.st_mtime_ns))
        payload = f"dir|{file_count}|{total_size}|{newest_mtime_ns}".encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        return {
            "kind": "directory",
            "path": str(path),
            "file_count": file_count,
            "total_size_bytes": total_size,
            "newest_mtime_ns": newest_mtime_ns,
            "fingerprint_sha256": digest,
        }

    st = path.stat()
    head, tail = _file_head_tail_hash(path, chunk_size=1024 * 1024)
    payload = json.dumps(
        {
            "size_bytes": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
            "head_sha256": head,
            "tail_sha256": tail,
        },
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "kind": "file",
        "path": str(path),
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "head_sha256": head,
        "tail_sha256": tail,
        "fingerprint_sha256": digest,
    }


def _file_head_tail_hash(path: Path, *, chunk_size: int) -> Tuple[str, str]:
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(chunk_size)
        if size > chunk_size:
            f.seek(max(0, size - chunk_size))
            tail = f.read(chunk_size)
        else:
            tail = head
    return hashlib.sha256(head).hexdigest(), hashlib.sha256(tail).hexdigest()


def _safe_status(status: str) -> str:
    if status in {"supported", "needs_input", "unsupported"}:
        return status
    return "needs_input"


def _safe_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out < 0:
        return 0.0
    if out > 1:
        return 1.0
    return round(out, 3)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default
