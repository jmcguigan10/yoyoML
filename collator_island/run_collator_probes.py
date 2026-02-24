#!/usr/bin/env python3
"""Collator probe runner adapter: probe_request_bundle.v1 -> probe_result_bundle.v1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mmtool.probe_runner import (  # noqa: E402
    dump_json,
    load_json,
    run_probe_bundle,
    validate_probe_request_bundle,
    validate_probe_result_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_collator_probes",
        description="Execute collator probe requests and emit probe result bundle JSON.",
    )
    p.add_argument(
        "--probe-request-in",
        required=True,
        help="Path to probe_request_bundle.v1 JSON file.",
    )
    p.add_argument(
        "--probe-result-out",
        required=True,
        help="Output path for probe_result_bundle.v1 JSON file (or directory).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    req = load_json(args.probe_request_in)
    req_errors = validate_probe_request_bundle(req)
    if req_errors:
        print("Probe request validation failed:")
        for err in req_errors:
            print(f"  - {err}")
        return 2

    result = run_probe_bundle(req)
    res_errors = validate_probe_result_bundle(result)
    if res_errors:
        print("Probe result validation failed:")
        for err in res_errors:
            print(f"  - {err}")
        return 3

    out = dump_json(args.probe_result_out, result)
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    print(
        "Probe result bundle written to "
        f"{out} (results={summary.get('result_count')}, "
        f"success={summary.get('success_count')}, failed={summary.get('failed_count')})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
