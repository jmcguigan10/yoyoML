from __future__ import annotations

import configparser
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource
from .base import BaseInspector


class IniInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(f"Loaded only first {ctx.max_bytes_to_load:,} bytes.")

        text = data.decode("utf-8", errors="replace")

        parser = configparser.ConfigParser()
        parser.read_string(text)

        sections = {}
        for sec in parser.sections()[: ctx.max_nested_items]:
            items = dict(parser.items(sec))
            # cap items
            if len(items) > ctx.max_nested_items:
                items = dict(list(items.items())[: ctx.max_nested_items])
                warnings.append(f"Section '{sec}': truncated items.")
            sections[sec] = items

        summary: Dict[str, Any] = {
            "format": "ini",
            "sections": list(parser.sections()),
            "section_count": len(parser.sections()),
            "items_by_section": sections,
        }
        return summary, warnings
