from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

import xml.etree.ElementTree as ET

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource
from ..utils.pretty import first_n
from .base import BaseInspector


class XmlInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []

        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(f"Loaded only first {ctx.max_bytes_to_load:,} bytes.")

        text = data.decode("utf-8", errors="replace")

        root = ET.fromstring(text)

        tag_counter: Counter[str] = Counter()
        attr_counter: Counter[str] = Counter()

        max_nodes = 5000
        nodes = 0
        for elem in root.iter():
            tag_counter[elem.tag] += 1
            for k in elem.attrib.keys():
                attr_counter[k] += 1
            nodes += 1
            if nodes >= max_nodes:
                warnings.append(f"Stopped counting after {max_nodes} nodes.")

        # children preview
        children = list(root)[: min(len(list(root)), 20)]
        child_preview = [{"tag": c.tag, "attrib": dict(list(c.attrib.items())[:10])} for c in children]

        summary: Dict[str, Any] = {
            "format": "xml",
            "root_tag": root.tag,
            "node_count_counted": nodes,
            "top_tags": tag_counter.most_common(20),
            "top_attributes": attr_counter.most_common(20),
            "root_children_preview": child_preview,
        }

        return summary, warnings
