#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def run(cmd: list[str], *, cwd: Path) -> None:
    print("$", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.strip())
        raise SystemExit(proc.returncode)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="test_feedback_loop_e2e",
        description="Run full feedback-loop E2E test: ingestor -> recommender -> collator probe runner -> recommender.",
    )
    parser.add_argument(
        "--dataset",
        default="sample_data/people.csv",
        help="Dataset path relative to repo root for ingestion test.",
    )
    parser.add_argument(
        "--out-dir",
        default="tmp/e2e_feedback_loop",
        help="Output directory relative to repo root.",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    py = sys.executable

    # 1) Regenerate sample data to make the test self-contained.
    run([py, "scripts/generate_test_data.py"], cwd=root)

    dataset_path = (root / args.dataset).resolve()
    assert_true(dataset_path.exists(), f"Dataset does not exist: {dataset_path}")

    # 2) Ingestor diagnostics bundle.
    diag_path = out_dir / "diagnostic_bundle.round1.json"
    run(
        [
            py,
            "inspect_data.py",
            str(dataset_path),
            "--target-col",
            "is_active",
            "--task-hint",
            "binary_classification",
            "--diagnostic-bundle-out",
            str(diag_path),
        ],
        cwd=root,
    )
    diag = load_json(diag_path)
    assert_true(diag.get("schema_version") == "diagnostic_bundle.v1", "Invalid diagnostic bundle schema_version")

    # 3) Recommender round 1 -> request probes.
    rec1 = out_dir / "recommendation_bundle.round1.json"
    loop1 = out_dir / "loop_decision.round1.json"
    req1 = out_dir / "probe_request.round1.json"
    run(
        [
            py,
            "recommend_models.py",
            "--diagnostic-in",
            str(diag_path),
            "--recommendation-out",
            str(rec1),
            "--loop-decision-out",
            str(loop1),
            "--probe-request-out",
            str(req1),
            "--loop-run-id",
            "e2e_loop",
            "--round-index",
            "1",
        ],
        cwd=root,
    )

    rec1_obj = load_json(rec1)
    loop1_obj = load_json(loop1)
    req1_obj = load_json(req1)
    assert_true(rec1_obj.get("schema_version") == "recommendation_bundle.v1", "Invalid recommendation bundle schema")
    assert_true(loop1_obj.get("schema_version") == "loop_decision_bundle.v1", "Invalid loop decision schema")
    assert_true(req1_obj.get("schema_version") == "probe_request_bundle.v1", "Invalid probe request schema")
    assert_true(
        (loop1_obj.get("decision") or {}).get("action") == "request_probes",
        "Round1 should request probes for degraded/blocked datasets.",
    )
    assert_true(len(req1_obj.get("requests", [])) > 0, "Probe request bundle should contain at least one request.")

    # 4) Collator probe runner executes request bundle.
    res1 = out_dir / "probe_result.round1.json"
    run(
        [
            py,
            "collator_island/run_collator_probes.py",
            "--probe-request-in",
            str(req1),
            "--probe-result-out",
            str(res1),
        ],
        cwd=root,
    )
    res1_obj = load_json(res1)
    assert_true(res1_obj.get("schema_version") == "probe_result_bundle.v1", "Invalid probe result schema")
    assert_true((_safe_int((res1_obj.get("summary") or {}).get("result_count")) > 0), "Expected probe results.")

    # 5) Recommender round 2 with feedback.
    # Use high min-confidence-gain to force deterministic await_operator behavior.
    rec2 = out_dir / "recommendation_bundle.round2.json"
    loop2 = out_dir / "loop_decision.round2.json"
    req2 = out_dir / "probe_request.round2.json"
    if req2.exists():
        req2.unlink()

    run(
        [
            py,
            "recommend_models.py",
            "--diagnostic-in",
            str(diag_path),
            "--probe-result-in",
            str(res1),
            "--recommendation-out",
            str(rec2),
            "--loop-decision-out",
            str(loop2),
            "--probe-request-out",
            str(req2),
            "--loop-run-id",
            "e2e_loop",
            "--round-index",
            "2",
            "--min-confidence-gain",
            "0.2",
        ],
        cwd=root,
    )
    rec2_obj = load_json(rec2)
    loop2_obj = load_json(loop2)
    action2 = str((loop2_obj.get("decision") or {}).get("action"))
    assert_true(rec2_obj.get("schema_version") == "recommendation_bundle.v1", "Round2 recommendation schema mismatch")
    assert_true(loop2_obj.get("schema_version") == "loop_decision_bundle.v1", "Round2 loop decision schema mismatch")
    assert_true(action2 == "await_operator", f"Expected await_operator in round2, got {action2!r}")
    assert_true(not req2.exists(), "Round2 probe request should not be emitted when action is not request_probes.")

    print("\nE2E feedback loop test passed.")
    print(f"Artifacts in: {out_dir}")
    return 0


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
