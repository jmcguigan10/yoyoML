#!/usr/bin/env python3
"""Convenience wrapper to run the model selector island without installing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MSRC = ROOT / "model_selector_island" / "src"
sys.path.insert(0, str(MSRC))

from model_selector.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
