from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

try:  # py3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore


def load_config(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suffix = p.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    elif suffix == ".toml":
        if tomllib is None:
            raise RuntimeError("tomllib not available; use Python 3.11+ or install tomli")
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported config format: {p}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Top-level config must be a mapping, got {type(data)}")
    return data


def dump_config(data: Dict[str, Any], fmt: str = "toml") -> str:
    fmt = fmt.lower()
    if fmt == "yaml":
        return yaml.safe_dump(data, sort_keys=False)
    if fmt == "toml":
        return _dump_toml(data)
    raise ValueError("fmt must be 'toml' or 'yaml'")


def _fmt_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    return f'"{str(v)}"'


def _fmt_list(vals: list[Any]) -> str:
    items = []
    for v in vals:
        if isinstance(v, list):
            items.append(_fmt_list(v))
        elif isinstance(v, dict):
            items.append("{" + ", ".join(f"{k} = {_fmt_scalar(val)}" for k, val in v.items()) + "}")
        else:
            items.append(_fmt_scalar(v))
    return "[" + ", ".join(items) + "]"


def _dump_table(data: Dict[str, Any], *, path: list[str] | None = None) -> list[str]:
    path = path or []
    prefix = ".".join(path) + "." if path else ""
    lines: list[str] = []
    for k, v in data.items():
        if isinstance(v, dict):
            header = f"{prefix}{k}" if prefix else k
            lines.append(f"[{header}]")
            lines.extend(_dump_table(v, path=path + [k]))
            lines.append("")  # spacer
        elif isinstance(v, list) and v and all(isinstance(it, dict) for it in v):
            for item in v:
                header = f"{prefix}{k}" if prefix else k
                lines.append(f"[[{header}]]")
                lines.extend(_dump_table(item, path=path + [k]))
                lines.append("")
        elif isinstance(v, list):
            lines.append(f"{k} = {_fmt_list(v)}")
        else:
            lines.append(f"{k} = {_fmt_scalar(v)}")
    return lines


def _dump_toml(data: Dict[str, Any]) -> str:
    lines = _dump_table(data)
    # Remove trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
