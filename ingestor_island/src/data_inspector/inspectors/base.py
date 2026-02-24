from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult, InspectionReport
from ..core.source import DataSource, PathSource


@dataclass
class BaseInspector:
    engine: Any  # InspectionEngine, imported lazily to avoid cycles

    def inspect(self, source: DataSource, detection: DetectionResult, ctx: InspectionContext) -> InspectionReport:
        report = InspectionReport(display_name=source.display_name, detection=detection)
        try:
            summary, warnings = self._inspect(source, detection, ctx)
            report.summary = summary
            for w in warnings:
                report.add_warning(w)
        except Exception as e:
            report.add_warning(f"Inspection failed: {e.__class__.__name__}: {e}")
        return report

    def _inspect(self, source: DataSource, detection: DetectionResult, ctx: InspectionContext) -> Tuple[Dict[str, Any], List[str]]:
        raise NotImplementedError

    def _maybe_file_size(self, source: DataSource) -> int | None:
        if isinstance(source, PathSource):
            try:
                return os.path.getsize(source.path)
            except Exception:
                return None
        return None

    def _read_all_bytes_limited(self, source: DataSource, limit: int) -> tuple[bytes, bool]:
        """Returns (data, truncated)."""
        with source.open_binary() as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            return data[:limit], True
        return data, False
