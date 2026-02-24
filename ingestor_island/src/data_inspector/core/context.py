from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class InspectionContext:
    """Controls how aggressively we parse and how much we print."""

    max_bytes_to_sniff: int = 256 * 1024     # how many bytes to sample for detection
    max_bytes_to_load: int = 10 * 1024 * 1024  # safety limit for in-memory loads (archives, compressed)
    max_rows: int = 8
    max_cols: int = 30
    max_depth: int = 6
    max_archive_members: int = 20
    max_nested_items: int = 40
    max_profile_rows: int = 2000
    max_profile_cols: int = 200
    recursive: bool = False

    # Security: never unpickle by default.
    unsafe_unpickle: bool = False

    # Optional semantics hints for ML diagnostics.
    enable_diagnostics: bool = True
    target_column: Optional[str] = None
    task_hint: Optional[str] = None
    time_column: Optional[str] = None
    group_column: Optional[str] = None
    split_column: Optional[str] = None
    id_columns: Tuple[str, ...] = ()
    objective_metric: Optional[str] = None
    assumption_auto_accept_threshold: float = 0.85
