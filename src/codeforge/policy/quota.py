"""Run quota (security invariant 11). Pure functions; the store counts, these decide."""

from __future__ import annotations

from datetime import datetime

# Outcomes that do not use up a User's Run quota: a Transient failure ("cannot generate now")
# and the quota refusal itself. Everything else counts, including Runs still in progress.
NOT_COUNTED: frozenset[str] = frozenset({"cannot_generate", "quota_exceeded"})


def counts_toward_quota(outcome: str | None) -> bool:
    return outcome not in NOT_COUNTED


def quota_allows(used: int, limit: int) -> bool:
    """True if one more Request fits. A non-positive limit refuses everything (fail closed)."""
    return limit > 0 and used < limit


def quota_window_start(now: datetime) -> datetime:
    """Start of the daily window: midnight of `now`'s day, in `now`'s timezone (UTC in use)."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)
