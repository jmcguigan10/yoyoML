from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

from .context import InspectionContext
from .detector import FileTypeDetector
from .registry import InspectorRegistry
from .report import InspectionReport
from .source import DataSource, PathSource


@dataclass
class InspectionEngine:
    detector: FileTypeDetector
    registry: InspectorRegistry
    diagnostics_runner: Any = None

    @classmethod
    def default(cls) -> "InspectionEngine":
        from ..diagnostics.runner import DiagnosticsRunner

        return cls(
            detector=FileTypeDetector(),
            registry=InspectorRegistry.default(),
            diagnostics_runner=DiagnosticsRunner.default(),
        )

    def inspect_source(self, source: DataSource, ctx: InspectionContext) -> InspectionReport:
        detection = self.detector.detect(source, ctx)
        inspector_cls = self.registry.get(detection.file_type)

        # Fall back to binary inspector if unknown/unregistered.
        if inspector_cls is None:
            from ..inspectors.binary import BinaryInspector

            inspector_cls = BinaryInspector

        inspector = inspector_cls(engine=self)
        report = inspector.inspect(source, detection, ctx)

        if self.diagnostics_runner is not None and ctx.enable_diagnostics:
            try:
                self.diagnostics_runner.apply(source, detection, report, ctx)
            except Exception as e:
                report.add_warning(f"Diagnostics failed: {e.__class__.__name__}: {e}")

        return report

    def iter_path_sources(self, path: Path, recursive: bool) -> Iterable[PathSource]:
        if path.is_file():
            yield PathSource(path)
            return

        if not path.is_dir():
            return

        if recursive:
            for p in sorted(path.rglob("*")):
                if p.is_file():
                    yield PathSource(p)
        else:
            for p in sorted(path.iterdir()):
                if p.is_file():
                    yield PathSource(p)

    def inspect_path(self, path: Path, ctx: InspectionContext) -> List[InspectionReport]:
        reports: List[InspectionReport] = []
        for src in self.iter_path_sources(path, ctx.recursive):
            reports.append(self.inspect_source(src, ctx))
        return reports
