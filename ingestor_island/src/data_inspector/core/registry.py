from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Type

from ..inspectors.base import BaseInspector


@dataclass
class InspectorRegistry:
    """Maps detected file types to inspector classes."""

    _mapping: Dict[str, Type[BaseInspector]]

    @classmethod
    def default(cls) -> "InspectorRegistry":
        # Imported lazily to avoid circular imports.
        from ..inspectors.archive import ZipInspector
        from ..inspectors.binary import BinaryInspector
        from ..inspectors.compressed import Bz2Inspector, GzipInspector
        from ..inspectors.excel import ExcelInspector
        from ..inspectors.html_tables import HtmlInspector
        from ..inspectors.ini import IniInspector
        from ..inspectors.json_like import JsonInspector, JsonlInspector, YamlInspector
        from ..inspectors.npz import NpzInspector
        from ..inspectors.sqlite_db import SqliteInspector
        from ..inspectors.tabular import DelimitedTextInspector
        from ..inspectors.text import KeyValueTextInspector, PlainTextInspector
        from ..inspectors.xml_like import XmlInspector

        mapping: Dict[str, Type[BaseInspector]] = {
            "zip": ZipInspector,
            "npz": NpzInspector,
            "gzip": GzipInspector,
            "bzip2": Bz2Inspector,
            "xlsx": ExcelInspector,
            "sqlite": SqliteInspector,
            "csv": DelimitedTextInspector,
            "tsv": DelimitedTextInspector,
            "delimited": DelimitedTextInspector,
            "json": JsonInspector,
            "jsonl": JsonlInspector,
            "yaml": YamlInspector,
            "xml": XmlInspector,
            "html": HtmlInspector,
            "ini": IniInspector,
            "text_kv": KeyValueTextInspector,
            "text": PlainTextInspector,
            "binary": BinaryInspector,
            "unknown": BinaryInspector,
            "parquet": BinaryInspector,
            "avro": BinaryInspector,
            "feather": BinaryInspector,
            "pickle": BinaryInspector,
        }
        return cls(mapping)

    def get(self, file_type: str) -> Optional[Type[BaseInspector]]:
        return self._mapping.get(file_type)
