"""Code policy (security invariants 4, 5). Pure: parse with `ast` only, never run anything.

An allowlist, applied to both the generated code and the generated tests:
- allow: pure standard-library modules, pytest, and the generated `solution` module;
- needs_approval: file access (`open`, `pathlib`, `io`) and network access;
- deny: everything else, including dangerous modules, dynamic execution, dunder access,
  reflection, parse failures and anything not listed.
"""

from __future__ import annotations

import ast
from typing import Literal

from pydantic import BaseModel

Verdict = Literal["allow", "needs_approval", "deny"]
_RANK: dict[str, int] = {"allow": 0, "needs_approval": 1, "deny": 2}
MAX_SOURCE_BYTES = 100_000  # generated modules for small tasks are far below this


class PolicyDecision(BaseModel):
    verdict: Verdict
    reasons: list[str]


MAX_NESTING = 100  # far deeper than any small generated function; stops pathological input

ALLOWED_MODULES: frozenset[str] = frozenset({
    "__future__", "abc", "array", "bisect", "calendar", "cmath", "collections", "copy",
    "dataclasses", "datetime", "decimal", "enum", "fractions", "functools", "heapq",
    "itertools", "json", "math", "numbers", "operator", "random", "re", "statistics",
    "string", "textwrap", "typing", "unicodedata",
    "pytest", "solution",  # the test runner and the generated module under test
})
FILE_MODULES: frozenset[str] = frozenset({"pathlib", "io"})
NETWORK_MODULES: frozenset[str] = frozenset({"socket", "urllib", "http", "requests"})
# Builtins that run strings as code or reach interpreter internals.
DENIED_NAMES: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "breakpoint",
    "__builtins__",
})
REFLECTION_CALLS: frozenset[str] = frozenset({"getattr", "setattr", "delattr"})


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    # ValueError: null bytes. RecursionError/MemoryError: pathological nesting. All fail closed.
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _deny(reason: str) -> PolicyDecision:
    return PolicyDecision(verdict="deny", reasons=[reason])


def evaluate_code_policy(source: str) -> PolicyDecision:
    """Decide allow / needs_approval / deny for one source file, without running it."""
    try:
        size = len(source.encode("utf-8"))
    except UnicodeEncodeError:  # e.g. lone surrogates: cannot be written for the sandbox
        return _deny("source is not valid UTF-8 text")
    if size > MAX_SOURCE_BYTES:
        return _deny(f"source too large ({size} bytes > {MAX_SOURCE_BYTES})")
    tree = _parse(source)
    if tree is None:
        return _deny("could not parse the source")
    if _depth(tree) > MAX_NESTING:
        return _deny(f"source nested deeper than {MAX_NESTING} levels")
    findings = [f for node in ast.walk(tree) for f in _check(node)]
    if not findings:
        return PolicyDecision(verdict="allow", reasons=[])
    return strictest(*(PolicyDecision(verdict=v, reasons=[r]) for v, r in findings))


def _depth(tree: ast.AST) -> int:
    """Deepest node nesting, computed without recursion."""
    deepest, stack = 0, [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        deepest = max(deepest, depth)
        if deepest > MAX_NESTING:
            break
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return deepest


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def _module_verdict(module: str) -> tuple[Verdict, str]:
    root = module.split(".")[0]
    if root in ALLOWED_MODULES:
        return "allow", ""
    if root in FILE_MODULES:
        return "needs_approval", f"import {module}: file access"
    if root in NETWORK_MODULES:
        return "needs_approval", f"import {module}: network access"
    return "deny", f"import {module}: module not on the allowlist"


def _check(node: ast.AST) -> list[tuple[Verdict, str]]:
    """Findings for one node; an empty list means nothing to report."""
    found: list[tuple[Verdict, str]] = []
    if isinstance(node, ast.Import):
        found += [_module_verdict(alias.name) for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        if node.level or not node.module:
            found.append(("deny", "relative import"))
        else:
            found.append(_module_verdict(node.module))
    elif isinstance(node, ast.Name):
        if node.id in DENIED_NAMES:
            found.append(("deny", f"use of {node.id}"))
        elif node.id == "open":
            found.append(("needs_approval", "open(): file access"))
        elif _is_dunder(node.id) and node.id != "__name__":
            found.append(("deny", f"dunder name {node.id}"))
    elif isinstance(node, ast.Attribute) and _is_dunder(node.attr):
        found.append(("deny", f"dunder attribute .{node.attr}"))
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in REFLECTION_CALLS:
        name = node.args[1] if len(node.args) > 1 else None
        if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
            found.append(("deny", f"{node.func.id}() with a computed attribute name"))
        elif _is_dunder(name.value):
            found.append(("deny", f"{node.func.id}() on dunder attribute {name.value}"))
    return [(v, r) for v, r in found if v != "allow"]


def strictest(*decisions: PolicyDecision) -> PolicyDecision:
    """Combine decisions: the strictest verdict wins; reasons are kept in order."""
    verdict = max((d.verdict for d in decisions), key=_RANK.__getitem__)
    reasons = [r for d in decisions for r in d.reasons]
    return PolicyDecision(verdict=verdict, reasons=reasons)


def defines_function(source: str, name: str) -> bool:
    """True if `source` defines a top-level function called `name`."""
    tree = _parse(source)
    if tree is None:
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        for node in tree.body
    )
