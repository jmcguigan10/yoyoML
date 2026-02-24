from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource
from ..utils.pretty import first_n
from .base import BaseInspector

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


def _depth(obj: Any, max_depth: int) -> int:
    if max_depth <= 0:
        return 0
    if isinstance(obj, dict):
        if not obj:
            return 1
        return 1 + max(_depth(v, max_depth - 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return 1
        return 1 + max(_depth(v, max_depth - 1) for v in obj[:25])
    return 1


def _type_name(x: Any) -> str:
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "bool"
    if isinstance(x, int) and not isinstance(x, bool):
        return "int"
    if isinstance(x, float):
        return "float"
    if isinstance(x, str):
        return "str"
    if isinstance(x, dict):
        return "object"
    if isinstance(x, list):
        return "array"
    return type(x).__name__


def _summarize_records(records: List[Any], max_keys: int = 40) -> Dict[str, Any]:
    key_counter: Counter[str] = Counter()
    type_counter_by_key: dict[str, Counter[str]] = defaultdict(Counter)

    for r in records:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            key_counter[k] += 1
            type_counter_by_key[k][_type_name(v)] += 1

    common_keys = [k for k, _ in key_counter.most_common(max_keys)]
    schema = {}
    for k in common_keys:
        schema[k] = {
            "present_in": int(key_counter[k]),
            "types": dict(type_counter_by_key[k]),
        }
    return {
        "record_count_sampled": len(records),
        "common_keys": common_keys,
        "schema_by_key": schema,
    }


class JsonInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []

        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(
                f"File exceeds {ctx.max_bytes_to_load:,} bytes; loaded only a prefix. JSON parsing may fail."
            )

        text = data.decode("utf-8", errors="replace")
        obj = json.loads(text)

        summary: Dict[str, Any] = {
            "format": "json",
            "top_level": type(obj).__name__,
            "depth_estimate": _depth(obj, ctx.max_depth),
        }

        if isinstance(obj, dict):
            keys = list(obj.keys())
            summary["keys"] = keys[: ctx.max_nested_items]
            if len(keys) > ctx.max_nested_items:
                warnings.append(f"Showing only first {ctx.max_nested_items} of {len(keys)} keys.")

            # Provide a small sample of values' types
            summary["value_types_sample"] = {
                k: _type_name(obj[k]) for k in first_n(keys, min(ctx.max_nested_items, 25))
            }

        elif isinstance(obj, list):
            summary["length"] = len(obj)
            sample = obj[: min(len(obj), ctx.max_nested_items)]
            summary["element_types_sample"] = dict(Counter(_type_name(x) for x in sample))
            if sample and all(isinstance(x, dict) for x in sample):
                summary["records_summary"] = _summarize_records(sample)
            summary["sample_items"] = sample[: min(5, len(sample))]

        else:
            summary["value_type"] = _type_name(obj)
            summary["value_preview"] = repr(obj)[:500]

        return summary, warnings


class JsonlInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        with source.open_binary() as f:
            raw = f.read(ctx.max_bytes_to_load)
        text = raw.decode("utf-8", errors="replace")

        lines = [ln for ln in text.splitlines() if ln.strip()]
        parsed: List[Any] = []
        bad = 0
        for ln in lines[: max(1, ctx.max_rows * 5)]:
            try:
                parsed.append(json.loads(ln))
            except Exception:
                bad += 1

        summary: Dict[str, Any] = {
            "format": "jsonl",
            "lines_sampled": min(len(lines), max(1, ctx.max_rows * 5)),
            "parsed": len(parsed),
            "failed": bad,
            "element_types": dict(Counter(_type_name(x) for x in parsed)),
        }

        if parsed and all(isinstance(x, dict) for x in parsed):
            summary["records_summary"] = _summarize_records(parsed[: ctx.max_nested_items])

        summary["sample_items"] = parsed[: min(5, len(parsed))]

        if len(raw) >= ctx.max_bytes_to_load:
            warnings.append(f"Stopped reading at {ctx.max_bytes_to_load:,} bytes.")

        return summary, warnings


class YamlInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        if yaml is None:
            return {"format": "yaml"}, ["PyYAML is not installed, so YAML parsing is disabled."]

        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(f"Loaded only first {ctx.max_bytes_to_load:,} bytes.")

        text = data.decode("utf-8", errors="replace")
        obj = yaml.safe_load(text)

        summary: Dict[str, Any] = {
            "format": "yaml",
            "top_level": type(obj).__name__,
            "depth_estimate": _depth(obj, ctx.max_depth),
        }

        if isinstance(obj, dict):
            keys = list(obj.keys())
            summary["keys"] = keys[: ctx.max_nested_items]
            summary["value_types_sample"] = {
                k: _type_name(obj[k]) for k in first_n(keys, min(ctx.max_nested_items, 25))
            }
        elif isinstance(obj, list):
            summary["length"] = len(obj)
            sample = obj[: min(len(obj), ctx.max_nested_items)]
            summary["element_types_sample"] = dict(Counter(_type_name(x) for x in sample))
            summary["sample_items"] = sample[: min(5, len(sample))]
        else:
            summary["value_preview"] = repr(obj)[:500]

        return summary, warnings
