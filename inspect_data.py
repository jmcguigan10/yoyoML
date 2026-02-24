#!/usr/bin/env python3
"""Convenience wrapper for running the ingestor island without installation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INGESTOR_SRC = ROOT / "ingestor_island" / "src"
sys.path.insert(0, str(INGESTOR_SRC))

from data_inspector.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
