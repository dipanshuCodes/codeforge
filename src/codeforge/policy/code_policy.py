"""Code policy. Pure functions: parse with `ast` only, never compile or run anything.

L1 stub: parse failure → deny; everything else → needs_approval, so nothing runs without a
human until the R2 allowlist replaces `_L1_STUB_DECISION`.
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


_L1_STUB_DECISION = PolicyDecision(
    verdict="needs_approval",
    reasons=["L1 policy stub: all code needs approval until the R2 allowlist exists"],
)


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
    if _parse(source) is None:
        return _deny("could not parse the source")
    return _L1_STUB_DECISION.model_copy(deep=True)


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
