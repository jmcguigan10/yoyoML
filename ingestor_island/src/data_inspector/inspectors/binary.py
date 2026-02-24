from __future__ import annotations

import pickle
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource
from ..utils.text import ascii_preview, hex_preview
from .base import BaseInspector


class BinaryInspector(BaseInspector):
    """Fallback inspector for binary/unknown formats."""

    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        size = self._maybe_file_size(source)

        data, truncated = self._read_all_bytes_limited(source, min(ctx.max_bytes_to_load, 256 * 1024))
        if truncated:
            warnings.append(f"Read only first {len(data):,} bytes for preview (truncated).")

        summary: Dict[str, Any] = {
            "size_bytes": size,
            "preview": {
                "hex": hex_preview(data, max_len=96),
                "ascii": ascii_preview(data, max_len=240),
            },
        }

        if detection.file_type == "pickle":
            if ctx.unsafe_unpickle:
                # This is unsafe by design, hence the flag.
                try:
                    obj = pickle.loads(data)  # nosec - user explicitly opted in
                    summary["unpickled_type"] = type(obj).__name__
                    summary["unpickled_repr"] = repr(obj)[:500]
                except Exception as e:
                    warnings.append(f"Unpickle failed: {e.__class__.__name__}: {e}")
            else:
                warnings.append("Pickle detected. Not unpickling without --unsafe-unpickle.")

        # Known-but-not-parsed binary types
        if detection.file_type in {"parquet", "avro", "feather"}:
            warnings.append(
                f"Detected {detection.file_type}. This pipeline doesn't parse it unless you add optional dependencies."
            )

        return summary, warnings
