from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class DiagnosticFinding:
    key: str
    title: str
    status: str
    confidence: float
    summary: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["confidence"] = round(float(out["confidence"]), 3)
        return out
