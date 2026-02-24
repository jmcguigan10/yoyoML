from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..core.report import InspectionReport
from ..utils.pretty import safe_json, truncate


@dataclass
class TerminalPrinter:
    max_summary_chars: int = 6000

    def print_reports(self, reports: Iterable[InspectionReport]) -> None:
        for r in reports:
            self.print_report(r)

    def print_report(self, report: InspectionReport) -> None:
        det = report.detection
        bar = "=" * 90
        print(bar)
        print(report.display_name)
        print(f"Detected: {det.file_type} (confidence {det.confidence:.0%})" + (f" | subtype: {det.subtype}" if det.subtype else ""))
        print(f"Reason: {truncate(det.reason, 300)}")
        if det.details:
            print("Details:")
            print(truncate(safe_json(det.details, max_len=1200), 1200))

        if report.warnings:
            print("Warnings:")
            for w in report.warnings:
                print(f"  - {w}")

        if report.summary:
            print("Summary:")
            print(truncate(safe_json(report.summary, max_len=self.max_summary_chars), self.max_summary_chars))
        else:
            print("Summary: (none)")

        if report.diagnostics:
            self._print_diagnostics(report.diagnostics)

    def _print_diagnostics(self, diagnostics: dict) -> None:
        print("Diagnostics:")
        if not diagnostics.get("enabled", True):
            print("  disabled")
            return

        coverage = diagnostics.get("coverage", {})
        supported = coverage.get("supported_vital_checks")
        total = coverage.get("total_vital_checks")
        if supported is not None and total is not None:
            print(f"  vital_supported: {supported}/{total}")

        assumptions = diagnostics.get("assumptions")
        if isinstance(assumptions, list) and assumptions:
            auto = len([a for a in assumptions if isinstance(a, dict) and a.get("status") == "auto_accept"])
            verify = len(
                [
                    a
                    for a in assumptions
                    if isinstance(a, dict) and a.get("status") in {"needs_user_verification", "unresolved"}
                ]
            )
            print(f"  assumptions: auto_accept={auto}, verify_or_unresolved={verify}")

        profile = diagnostics.get("profile")
        if isinstance(profile, dict):
            rows = profile.get("rows_profiled")
            cols = profile.get("columns_profiled")
            table = profile.get("table_name")
            if rows is not None and cols is not None:
                table_part = f", table={table}" if table else ""
                print(f"  profile_shape: rows={rows}, cols={cols}{table_part}")
            warnings = profile.get("parse_warnings") or []
            for w in warnings[:3]:
                print(f"  profile_warning: {truncate(str(w), 140)}")

        findings = diagnostics.get("findings", [])
        for item in findings:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", item.get("key", "unknown")))
            status = str(item.get("status", "unknown"))
            conf = item.get("confidence")
            summary = truncate(str(item.get("summary", "")), 170)
            if conf is None:
                print(f"  - [{status}] {title}: {summary}")
            else:
                print(f"  - [{status}] {title} ({float(conf):.2f}): {summary}")
