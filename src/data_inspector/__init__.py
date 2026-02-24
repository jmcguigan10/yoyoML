"""Compatibility shim for relocated ingestor package.

Canonical implementation now lives in:
`ingestor_island/src/data_inspector`.
"""

from __future__ import annotations

from pathlib import Path

_REAL_PACKAGE = (
    Path(__file__).resolve().parents[2] / "ingestor_island" / "src" / "data_inspector"
)
if _REAL_PACKAGE.is_dir():
    __path__.append(str(_REAL_PACKAGE))

from .cli import main

__all__ = ["main"]
