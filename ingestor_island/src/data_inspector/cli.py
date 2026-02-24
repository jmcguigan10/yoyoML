from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .core.context import InspectionContext
from .core.engine import InspectionEngine
from .exchange import build_diagnostic_bundle
from .printers.terminal import TerminalPrinter


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="data_inspector",
        description="Heuristic inspector for common data file formats (prints detected type + structure).",
    )
    p.add_argument("path", nargs="?", default=".", help="File or directory to inspect")
    p.add_argument("--recursive", action="store_true", help="Recurse into subdirectories")
    p.add_argument("--max-rows", type=int, default=8, help="Max sample rows to show for tabular-ish formats")
    p.add_argument("--max-cols", type=int, default=30, help="Max columns to display for tabular-ish formats")
    p.add_argument("--max-depth", type=int, default=6, help="Max nesting depth to summarize for structured formats")
    p.add_argument("--max-archive-members", type=int, default=20, help="Max members to list/inspect inside archives")
    p.add_argument("--max-bytes-sniff", type=int, default=256 * 1024, help="Bytes to read for detection")
    p.add_argument("--max-bytes-load", type=int, default=10 * 1024 * 1024, help="Max bytes to load into memory when needed")
    p.add_argument("--max-profile-rows", type=int, default=2000, help="Rows to profile for diagnostics")
    p.add_argument("--max-profile-cols", type=int, default=200, help="Columns to profile for diagnostics")
    p.add_argument("--unsafe-unpickle", action="store_true", help="Allow unpickling .pkl files (dangerous)")
    p.add_argument("--no-diagnostics", action="store_true", help="Disable ML-readiness diagnostics stage")
    p.add_argument("--target-col", default=None, help="Optional target column hint for diagnostics")
    p.add_argument("--task-hint", default=None, help="Optional task hint (e.g. regression, binary, multiclass)")
    p.add_argument("--time-col", default=None, help="Optional time column hint")
    p.add_argument("--group-col", default=None, help="Optional group/entity column hint")
    p.add_argument("--split-col", default=None, help="Optional train/val/test split column hint")
    p.add_argument("--id-cols", default=None, help="Comma-separated identifier columns to exclude from feature checks")
    p.add_argument("--metric", default=None, help="Optional objective metric hint (e.g. pr_auc, rmse)")
    p.add_argument("--assumptions-out", default=None, help="Write inferred assumptions JSON to this file (or directory)")
    p.add_argument(
        "--diagnostic-bundle-out",
        default=None,
        help="Write normalized diagnostic bundle JSON (diagnostic_bundle.v1) to this file (or directory)",
    )
    p.add_argument(
        "--strict-assumptions",
        action="store_true",
        help="Exit non-zero when assumptions require verification or are unresolved",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    id_cols = tuple(x.strip() for x in (args.id_cols or "").split(",") if x.strip())

    ctx = InspectionContext(
        max_bytes_to_sniff=args.max_bytes_sniff,
        max_bytes_to_load=args.max_bytes_load,
        max_rows=args.max_rows,
        max_cols=args.max_cols,
        max_depth=args.max_depth,
        max_archive_members=args.max_archive_members,
        max_profile_rows=args.max_profile_rows,
        max_profile_cols=args.max_profile_cols,
        recursive=args.recursive,
        unsafe_unpickle=args.unsafe_unpickle,
        enable_diagnostics=not args.no_diagnostics,
        target_column=args.target_col,
        task_hint=args.task_hint,
        time_column=args.time_col,
        group_column=args.group_col,
        split_column=args.split_col,
        id_columns=id_cols,
        objective_metric=args.metric,
    )

    path = Path(args.path).expanduser()
    if not path.exists():
        raise SystemExit(f"Path not found: {path}")

    engine = InspectionEngine.default()
    reports = engine.inspect_path(path, ctx)

    TerminalPrinter().print_reports(reports)
    unresolved = _count_unverified_assumptions(reports)

    if args.assumptions_out:
        out_path = _write_assumptions_file(reports, path, args.assumptions_out)
        print(
            f"Assumptions written to {out_path}. "
            "Please verify entries marked 'needs_user_verification' or 'unresolved'."
        )

    if args.diagnostic_bundle_out:
        out_path = _write_diagnostic_bundle_file(reports, path, args.diagnostic_bundle_out)
        print(f"Diagnostic bundle written to {out_path}.")

    if args.strict_assumptions and unresolved > 0:
        print(f"Strict assumptions mode: {unresolved} assumptions still need user verification.")
        return 2

    return 0


def _write_assumptions_file(reports, input_path: Path, out_arg: str) -> Path:
    out = _resolve_json_output_path(out_arg, default_name="assumptions.json")

    records = []
    verify_count = 0
    for r in reports:
        diagnostics = r.diagnostics if isinstance(r.diagnostics, dict) else {}
        assumptions = diagnostics.get("assumptions", []) if isinstance(diagnostics, dict) else []
        if not isinstance(assumptions, list):
            assumptions = []
        for a in assumptions:
            if isinstance(a, dict) and a.get("status") in {"needs_user_verification", "unresolved"}:
                verify_count += 1
        records.append(
            {
                "display_name": r.display_name,
                "detected_type": r.detection.file_type,
                "assumptions": assumptions,
            }
        )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "summary": {
            "file_count": len(records),
            "assumptions_needing_verification": verify_count,
        },
        "files": records,
    }

    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _write_diagnostic_bundle_file(reports, input_path: Path, out_arg: str) -> Path:
    out = _resolve_json_output_path(out_arg, default_name="diagnostic_bundle.json")
    payload = build_diagnostic_bundle(reports, input_path)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _count_unverified_assumptions(reports) -> int:
    count = 0
    for r in reports:
        diagnostics = r.diagnostics if isinstance(r.diagnostics, dict) else {}
        assumptions = diagnostics.get("assumptions", []) if isinstance(diagnostics, dict) else []
        if not isinstance(assumptions, list):
            continue
        for a in assumptions:
            if isinstance(a, dict) and a.get("status") in {"needs_user_verification", "unresolved"}:
                count += 1
    return count


def _resolve_json_output_path(out_arg: str, *, default_name: str) -> Path:
    out = Path(out_arg).expanduser()
    if out.exists() and out.is_dir():
        out = out / default_name
    elif out.suffix.lower() != ".json":
        out.mkdir(parents=True, exist_ok=True)
        out = out / default_name
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
