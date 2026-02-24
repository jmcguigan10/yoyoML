from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource
from ..utils.pretty import truncate
from .base import BaseInspector


_KV_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*[:=]\s*(.+?)\s*$")


class KeyValueTextInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(f"Loaded only first {ctx.max_bytes_to_load:,} bytes.")

        text = data.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]

        kv: Dict[str, Any] = {}
        for ln in lines[: 5000]:
            m = _KV_RE.match(ln)
            if not m:
                continue
            k, v = m.group(1), m.group(2)
            if k in kv:
                # keep the first; humans love duplicates for some reason
                continue
            kv[k] = v

        summary: Dict[str, Any] = {
            "format": "text_kv",
            "line_count_sampled": len(lines),
            "keys": list(kv.keys())[: ctx.max_nested_items],
            "items": dict(list(kv.items())[: ctx.max_nested_items]),
        }
        if len(kv) > ctx.max_nested_items:
            warnings.append(f"Showing only first {ctx.max_nested_items} key-value pairs.")
        return summary, warnings


class PlainTextInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(f"Loaded only first {ctx.max_bytes_to_load:,} bytes.")

        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()

        # Simple stats
        nonempty = [ln for ln in lines if ln.strip()]
        lengths = [len(ln) for ln in nonempty[:5000]]
        avg_len = sum(lengths) / len(lengths) if lengths else 0

        # character frequency hints
        chars = Counter()
        for ln in nonempty[:2000]:
            for ch in ",;|\t":
                if ch in ln:
                    chars[ch] += 1

        summary: Dict[str, Any] = {
            "format": "text",
            "lines": len(lines),
            "nonempty_lines": len(nonempty),
            "avg_line_length_estimate": round(avg_len, 2),
            "common_separators_in_lines": dict(chars),
            "sample_lines": [truncate(ln, 200) for ln in nonempty[: ctx.max_rows]],
        }
        return summary, warnings
