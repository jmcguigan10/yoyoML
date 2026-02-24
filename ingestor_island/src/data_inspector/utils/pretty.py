from __future__ import annotations

import json
from typing import Any, Iterable


def truncate(s: str, max_len: int = 200) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def safe_json(obj: Any, max_len: int = 800) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        s = repr(obj)
    return truncate(s, max_len=max_len)


def first_n(items: Iterable[Any], n: int) -> list[Any]:
    out = []
    for i, x in enumerate(items):
        if i >= n:
            break
        out.append(x)
    return out
