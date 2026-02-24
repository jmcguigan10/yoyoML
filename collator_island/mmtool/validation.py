from __future__ import annotations

import ast
from typing import List

from .errors import ValidationError

# This is NOT a sandbox. It's just enough structure checks to avoid
# accidentally assembling obviously dangerous constructs.
BANNED_CALLS = {"exec", "eval", "compile", "__import__"}
BANNED_ATTRS = {"__dict__", "__class__", "__globals__", "__code__", "__getattribute__", "__subclasses__", "__mro__", "__bases__"}
BANNED_MODULES = {"subprocess", "ctypes"}

ALLOWED_TOPLEVEL_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Raise,
    ast.Assert,
    ast.Pass,
    ast.Break,
    ast.Continue,
    ast.Return,
    ast.Match,  # py3.10+
)


class SnippetValidator(ast.NodeVisitor):
    """Basic policy checks for assembled snippets."""

    def __init__(self, *, snippet_name: str):
        self.snippet_name = snippet_name
        self.errors: List[str] = []

    def fail(self, node: ast.AST, msg: str) -> None:
        line = getattr(node, "lineno", "?")
        self.errors.append(f"[{self.snippet_name}:{line}] {msg}")

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            self.fail(node, f"Call to banned function '{node.func.id}'.")
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.attr, str) and node.func.attr in BANNED_ATTRS:
                self.fail(
                    node,
                    f"Call via dunder attribute '{node.func.attr}' is blocked.",
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.attr, str) and node.attr in BANNED_ATTRS:
            self.fail(node, f"Dunder attribute access '{node.attr}' is blocked.")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in BANNED_MODULES:
                self.fail(node, f"Import of banned module '{root}'.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".", 1)[0]
            if root in BANNED_MODULES:
                self.fail(node, f"Import-from banned module '{root}'.")
        self.generic_visit(node)


def count_toplevel_functions(tree: ast.Module) -> int:
    return sum(
        isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) for stmt in tree.body
    )


def validate_one_function_per_file(tree: ast.Module, snippet_name: str) -> None:
    n = count_toplevel_functions(tree)
    if n > 1:
        raise ValidationError(
            f"[{snippet_name}] Snippet defines {n} top-level functions; "
            "prototype rule is <= 1 function per .txt snippet."
        )


def validate_snippet(tree: ast.Module, snippet_name: str) -> None:
    # Check top-level structure first
    for stmt in tree.body:
        if not isinstance(stmt, ALLOWED_TOPLEVEL_NODES):
            raise ValidationError(
                f"[{snippet_name}:{getattr(stmt, 'lineno', '?')}] "
                f"Top-level node '{type(stmt).__name__}' not allowed."
            )

    # Then run deep validation
    v = SnippetValidator(snippet_name=snippet_name)
    v.visit(tree)
    if v.errors:
        raise ValidationError("Snippet failed validation:\n" + "\n".join(v.errors))
