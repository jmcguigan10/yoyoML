from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class DetectionResult:
    file_type: str
    confidence: float
    reason: str
    subtype: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InspectionReport:
    """What we learned about a file."""

    display_name: str
    detection: DetectionResult
    summary: Dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
