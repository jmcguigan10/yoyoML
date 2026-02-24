from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .errors import CollisionError
from .snippets import Snippet
from .validation import validate_snippet


def _import_key(node: ast.AST) -> str:
    """Create a stable string key for import nodes so we can dedupe."""
    if isinstance(node, ast.Import):
        parts = []
        for a in node.names:
            parts.append(f"{a.name} as {a.asname}" if a.asname else a.name)
        return "import " + ", ".join(parts)

    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        parts = []
        for a in node.names:
            parts.append(f"{a.name} as {a.asname}" if a.asname else a.name)
        lvl = "." * (node.level or 0)
        return f"from {lvl}{mod} import " + ", ".join(parts)

    return repr(node)


def _defined_toplevel_names(tree: ast.Module) -> Set[str]:
    names: Set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets: List[ast.expr] = []
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            else:  # AnnAssign
                targets = [stmt.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


class SnippetAssembler:
    """Validate + assemble multiple snippets into a single python module."""

    def __init__(
        self,
        snippets: Iterable[Snippet] | None = None,
        *,
        module_docstring: Optional[str] = None,
    ) -> None:
        self._snippets: List[Snippet] = list(snippets) if snippets else []
        self.module_docstring = module_docstring

    def add_snippet(self, snippet: Snippet) -> None:
        self._snippets.append(snippet)

    def extend(self, snippets: Iterable[Snippet]) -> None:
        self._snippets.extend(snippets)

    def assemble(self) -> ast.Module:
        import_nodes: List[ast.AST] = []
        body_nodes: List[ast.AST] = []
        import_seen: Set[str] = set()

        defined_global: Dict[str, str] = {}

        for snip in self._snippets:
            tree = ast.parse(snip.code, filename=f"<{snip.name}>", mode="exec")
            validate_snippet(tree, snip.name)

            for name in _defined_toplevel_names(tree):
                if name in defined_global:
                    raise CollisionError(
                        f"Name collision: '{name}' defined in both '{defined_global[name]}' and '{snip.name}'."
                    )
                defined_global[name] = snip.name

            for stmt in tree.body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    k = _import_key(stmt)
                    if k not in import_seen:
                        import_seen.add(k)
                        import_nodes.append(stmt)
                else:
                    body_nodes.append(stmt)

        final_body: List[ast.stmt] = []

        if self.module_docstring:
            final_body.append(ast.Expr(value=ast.Constant(self.module_docstring)))

        final_body.extend(import_nodes)  # type: ignore[arg-type]
        final_body.extend(body_nodes)  # type: ignore[arg-type]

        mod = ast.Module(body=final_body, type_ignores=[])
        ast.fix_missing_locations(mod)
        return mod

    def write(self, out_path: str | Path) -> None:
        module = self.assemble()
        write_module_py(module, out_path)


def write_module_py(module: ast.Module, out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        code = ast.unparse(module)  # py3.9+
    except AttributeError as e:
        raise RuntimeError("ast.unparse not available. Use Python 3.9+.") from e

    out_path.write_text(code + "\n", encoding="utf-8")
