from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TabularProfile:
    """Canonical in-memory representation for tabular diagnostics."""

    source_name: str
    detection_type: str
    dataframe: Any
    table_name: Optional[str] = None
    approx_total_rows: Optional[int] = None
    parse_warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        try:
            return int(self.dataframe.shape[0])
        except Exception:
            return 0

    @property
    def col_count(self) -> int:
        try:
            return int(self.dataframe.shape[1])
        except Exception:
            return 0

    @property
    def columns(self) -> List[str]:
        try:
            return [str(c) for c in list(self.dataframe.columns)]
        except Exception:
            return []
