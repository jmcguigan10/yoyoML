from __future__ import annotations

import bz2
import gzip
import os
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import BytesSource, DataSource, PathSource
from .base import BaseInspector


class _CompressedBase(BaseInspector):
    compressor_name: str = ""

    def _decompress_to_limit(self, source: DataSource, ctx: InspectionContext) -> tuple[bytes, bool]:
        raise NotImplementedError

    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []

        data, truncated = self._decompress_to_limit(source, ctx)
        if truncated:
            warnings.append(
                f"Decompressed output truncated at {ctx.max_bytes_to_load:,} bytes. Inner inspection may be partial."
            )

        inner_suffix = ""
        # e.g. file.csv.gz -> use .csv as inner suffix if possible
        if isinstance(source, PathSource):
            name = source.path.name
            if name.endswith(".gz") or name.endswith(".bz2") or name.endswith(".bzip2"):
                base = name.rsplit(".", 1)[0]
                inner_suffix = os.path.splitext(base)[1]
        inner = BytesSource(name=f"{source.display_name}::decompressed", data=data, suffix=inner_suffix)

        inner_report = self.engine.inspect_source(inner, ctx)

        summary: Dict[str, Any] = {
            "format": self.compressor_name,
            "decompressed_bytes": len(data),
            "inner": {
                "detection": {
                    "file_type": inner_report.detection.file_type,
                    "confidence": inner_report.detection.confidence,
                    "reason": inner_report.detection.reason,
                },
                "summary": inner_report.summary,
                "warnings": inner_report.warnings,
            },
        }
        return summary, warnings


class GzipInspector(_CompressedBase):
    compressor_name = "gzip"

    def _decompress_to_limit(self, source: DataSource, ctx: InspectionContext) -> tuple[bytes, bool]:
        with source.open_binary() as f:
            gz = gzip.GzipFile(fileobj=f)
            chunks = []
            total = 0
            while True:
                chunk = gz.read(64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > ctx.max_bytes_to_load:
                    data = b"".join(chunks)
                    return data[: ctx.max_bytes_to_load], True
            return b"".join(chunks), False


class Bz2Inspector(_CompressedBase):
    compressor_name = "bzip2"

    def _decompress_to_limit(self, source: DataSource, ctx: InspectionContext) -> tuple[bytes, bool]:
        with source.open_binary() as f:
            bz = bz2.BZ2File(f)
            chunks = []
            total = 0
            while True:
                chunk = bz.read(64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > ctx.max_bytes_to_load:
                    data = b"".join(chunks)
                    return data[: ctx.max_bytes_to_load], True
            return b"".join(chunks), False
