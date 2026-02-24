from __future__ import annotations

import ast
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .errors import RegistryError
from .validation import validate_one_function_per_file, validate_snippet


SCHEMA = """
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    relpath TEXT NOT NULL,
    kind TEXT NOT NULL,
    exports TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT ''
);
"""


@dataclass(frozen=True)
class SnippetMeta:
    name: str
    relpath: str
    kind: str
    exports: str = ""
    description: str = ""


def _detect_kind(tree: ast.Module) -> str:
    has_func = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in tree.body)
    has_class = any(isinstance(n, ast.ClassDef) for n in tree.body)
    if has_func and not has_class:
        return "function"
    if has_class and not has_func:
        return "class"
    if has_class and has_func:
        return "mixed"
    return "code"


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.executescript(SCHEMA)


def upsert_snippet(db_path: Path, meta: SnippetMeta) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO snippets(name, relpath, kind, exports, description)
            VALUES(?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                relpath=excluded.relpath,
                kind=excluded.kind,
                exports=excluded.exports,
                description=excluded.description;
            """,
            (meta.name, meta.relpath, meta.kind, meta.exports, meta.description),
        )


def build_db_from_txt_store(*, db_path: Path, txt_root: Path) -> int:
    """Scan txt_root for *.txt snippets, validate, and populate the DB."""
    init_db(db_path)

    # Keep the DB in sync with the txt_store. Stale rows are worse than useless.
    with sqlite3.connect(db_path) as con:
        con.execute("DELETE FROM snippets")

    if not txt_root.exists():
        raise RegistryError(f"txt_store root not found: {txt_root}")

    count = 0
    for path in sorted(txt_root.rglob("*.txt")):
        rel = path.relative_to(txt_root).as_posix()
        name = rel[:-4].replace("/", ".")  # strip .txt

        code = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(code, filename=f"<{name}>", mode="exec")
        except SyntaxError as e:
            raise RegistryError(f"Syntax error in snippet {name} ({rel}): {e}") from e

        validate_snippet(tree, name)
        validate_one_function_per_file(tree, name)

        kind = _detect_kind(tree)
        exports = ",".join(_toplevel_exports(tree))

        upsert_snippet(
            db_path,
            SnippetMeta(name=name, relpath=rel, kind=kind, exports=exports),
        )
        count += 1

    return count


def _toplevel_exports(tree: ast.Module) -> list[str]:
    exports: list[str] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            exports.append(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    exports.append(t.id)
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name):
                exports.append(stmt.target.id)
    return exports


class SnippetDB:
    def __init__(self, *, db_path: Path, txt_root: Path) -> None:
        self.db_path = db_path
        self.txt_root = txt_root

    def exists(self) -> bool:
        return self.db_path.exists()

    def get_relpath(self, name: str) -> str:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                "SELECT relpath FROM snippets WHERE name=?", (name,)
            ).fetchone()
        if not row:
            raise RegistryError(f"Snippet not found in registry: {name}")
        return str(row[0])

    def get_code(self, name: str) -> str:
        rel = self.get_relpath(name)
        path = self.txt_root / rel
        if not path.exists():
            raise RegistryError(
                f"Registry points to missing snippet file: {name} -> {rel}"
            )
        return path.read_text(encoding="utf-8")

    def list(self, prefix: str = "") -> list[str]:
        with sqlite3.connect(self.db_path) as con:
            if prefix:
                rows = con.execute(
                    "SELECT name FROM snippets WHERE name LIKE ? ORDER BY name", (prefix + "%",)
                ).fetchall()
            else:
                rows = con.execute("SELECT name FROM snippets ORDER BY name").fetchall()
        return [r[0] for r in rows]


def default_paths(project_root: Path) -> tuple[Path, Path]:
    """Return (db_path, txt_root) relative to a project root."""
    return project_root / "snippet_db" / "snippets.sqlite", project_root / "txt_store"


def build_db(txt_root: Path, db_path: Path) -> int:
    """Convenience wrapper used by the CLI."""
    return build_db_from_txt_store(db_path=db_path, txt_root=txt_root)
