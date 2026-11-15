"""Repair rules. Pure functions: parse with `ast` only, never run anything.

A Repair attempt is model output, so it is untrusted. These rules decide whether it may even
be sent on to the policy gate and the sandbox. They never trust the model's own description.
"""

from __future__ import annotations

import ast

from pydantic import BaseModel

# Names whose appearance means "this test may not really run". Counted on the whole tree so
# `pytest.mark.skip`, `pytest.skip(...)` and a bare imported `skip` are all seen.
_SKIP_NAMES = frozenset({"skip", "skipif", "xfail", "importorskip"})


class RepairDecision(BaseModel):
    accepted: bool
    reasons: list[str]


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def count_tests(source: str) -> int:
    """Tests pytest would collect by name: top-level `test*` functions and `test*` methods of
    `Test*` classes. A parametrized test counts once (known gap, plan 07)."""
    tree = _parse(source)
    if tree is None:
        return 0
    total = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            total += 1
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            total += sum(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test")
                for item in node.body
            )
    return total


def _is_raises(item: ast.withitem) -> bool:
    call = item.context_expr
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "raises"
    )


def count_assertions(source: str) -> int:
    """`assert` statements with a non-constant test, plus `with pytest.raises(...)` blocks.
    `assert True` checks nothing, so it doesn't count."""
    tree = _parse(source)
    if tree is None:
        return 0
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and not isinstance(node.test, ast.Constant):
            total += 1
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            total += sum(_is_raises(item) for item in node.items)
    return total


def _count_skips(source: str) -> int:
    tree = _parse(source)
    if tree is None:
        return 0
    return sum(
        (isinstance(n, ast.Attribute) and n.attr in _SKIP_NAMES)
        or (isinstance(n, ast.Name) and n.id in _SKIP_NAMES)
        for n in ast.walk(tree)
    )


def evaluate_repair(attempt: int, old_code: str, old_tests: str,
                    new_code: str, new_tests: str) -> RepairDecision:
    """Decide whether Repair attempt `attempt` (1 or 2) may go on to the policy gate.

    Attempt 1 changes the code only. Attempt 2 may also change the tests, but never to fewer
    tests, fewer real assertions or more skip/xfail markers.
    """
    reasons: list[str] = []
    if any(_parse(s) is None for s in (old_code, old_tests, new_code, new_tests)):
        return RepairDecision(accepted=False, reasons=["could not parse the code or tests"])
    if new_code == old_code and new_tests == old_tests:
        reasons.append("repair left the code and tests unchanged")
    if attempt <= 1:
        if new_tests != old_tests:
            reasons.append("repair 1 may change the code only; the tests were changed")
    else:
        if count_tests(new_tests) < count_tests(old_tests):
            reasons.append(
                f"repair reduced the number of tests ({count_tests(old_tests)} → {count_tests(new_tests)})")
        if count_assertions(new_tests) < count_assertions(old_tests):
            reasons.append(
                f"repair reduced the number of assertions "
                f"({count_assertions(old_tests)} → {count_assertions(new_tests)})")
        if _count_skips(new_tests) > _count_skips(old_tests):
            reasons.append("repair added a skip or xfail marker")
    return RepairDecision(accepted=not reasons, reasons=reasons)


def should_repair(outcome: str | None, repairs_tried: int, max_attempts: int,
                  serving_tier: str | None) -> bool:
    """Only real test failures are repaired, within the budget, and never on the Template
    tier (no model is available to ask)."""
    return (
        outcome == "tests_failed"
        and repairs_tried < max_attempts
        and serving_tier != "template"
    )
