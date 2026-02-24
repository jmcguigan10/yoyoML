from __future__ import annotations

import os
import zipfile
from dataclasses import asdict
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import BytesSource, DataSource, PathSource
from .base import BaseInspector


class ZipInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []

        # zipfile prefers a seekable file handle.
        if isinstance(source, PathSource):
            zf = zipfile.ZipFile(str(source.path))
        else:
            data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
            if truncated:
                warnings.append(f"Loaded only first {ctx.max_bytes_to_load:,} bytes. ZIP may be incomplete.")
            import io

            zf = zipfile.ZipFile(io.BytesIO(data))

        with zf:
            infos = zf.infolist()
            member_summaries = []
            inspected_members = []
            skipped_too_large = 0

            for info in infos[: ctx.max_archive_members]:
                member_summaries.append(
                    {
                        "name": info.filename,
                        "compressed_size": info.compress_size,
                        "uncompressed_size": info.file_size,
                    }
                )

                # Inspect small-ish members
                if info.file_size > ctx.max_bytes_to_load:
                    skipped_too_large += 1
                    continue
                if info.is_dir():
                    continue

                try:
                    data = zf.read(info.filename)
                    inner = BytesSource(
                        name=f"{source.display_name}::{info.filename}",
                        data=data,
                        suffix=os.path.splitext(info.filename)[1],
                    )
                    inner_report = self.engine.inspect_source(inner, ctx)
                    inspected_members.append(
                        {
                            "member": info.filename,
                            "detection": {
                                "file_type": inner_report.detection.file_type,
                                "confidence": inner_report.detection.confidence,
                                "reason": inner_report.detection.reason,
                            },
                            "summary": inner_report.summary,
                            "warnings": inner_report.warnings,
                        }
                    )
                except Exception as e:
                    warnings.append(f"Failed inspecting member {info.filename}: {e.__class__.__name__}: {e}")

            if len(infos) > ctx.max_archive_members:
                warnings.append(f"Listing only first {ctx.max_archive_members} members of {len(infos)}.")

            if skipped_too_large:
                warnings.append(f"Skipped {skipped_too_large} member(s) larger than max_bytes_to_load.")

            summary: Dict[str, Any] = {
                "format": "zip",
                "member_count": len(infos),
                "members": member_summaries,
                "inspected_members": inspected_members,
            }
            return summary, warnings
