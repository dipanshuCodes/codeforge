"""Outcome of a Run, decided in code from the real pytest result. Never from model prose."""

from __future__ import annotations

import re
from typing import Literal

Outcome = Literal[
    "tests_passed",
    "tests_failed",
    "timed_out",
    "denied",
    "rejected",
    "unsupported",
    "cannot_generate",
    "quota_exceeded",
]

_SUMMARY = re.compile(
    r"^=*\s*(\d+ (?:passed|failed|error|errors|skipped|deselected|xfailed|xpassed)\b.*?"
    r"|no tests ran.*?)\s*=*$"
)


_COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")


def at_least_one_test_passed(output: str) -> bool:
    """True if pytest's summary shows >= 1 passed and no failures or errors."""
    summary = pytest_summary_line(output)
    if summary is None:
        return False
    counts: dict[str, int] = {}
    for n, word in _COUNT.findall(summary):
        key = "error" if word.startswith("error") else word
        counts[key] = counts.get(key, 0) + int(n)
    return counts.get("passed", 0) > 0 and not counts.get("failed") and not counts.get("error")


def outcome_from_execution(exit_code: int | None, timed_out: bool, output: str) -> Outcome:
    """A pass needs exit code 0 AND at least one passing test (all-skipped or an early
    exit(0) is not a pass). A timeout wins over any exit code."""
    if timed_out:
        return "timed_out"
    if exit_code == 0 and at_least_one_test_passed(output):
        return "tests_passed"
    return "tests_failed"


def pytest_summary_line(output: str) -> str | None:
    """The last pytest summary line (e.g. '5 passed in 0.04s'), without '=' borders."""
    for line in reversed(output.splitlines()):
        match = _SUMMARY.match(line.strip())
        if match:
            return match.group(1).strip()
    return None
