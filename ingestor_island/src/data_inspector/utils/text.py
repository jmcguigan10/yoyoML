from __future__ import annotations

import re
from typing import Optional


def guess_encoding(sample: bytes) -> str:
    """Cheap encoding guess: try UTF-8 flavors, then latin-1."""
    for enc in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            sample.decode(enc)
            return enc
        except Exception:
            continue
    return "utf-8"


def ascii_preview(b: bytes, max_len: int = 200) -> str:
    s = b.decode("utf-8", errors="replace")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def hex_preview(b: bytes, max_len: int = 64) -> str:
    h = b[:max_len].hex()
    # group as pairs
    grouped = " ".join(h[i : i + 2] for i in range(0, len(h), 2))
    return grouped
