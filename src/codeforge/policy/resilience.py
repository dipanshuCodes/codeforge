"""Pure resilience rules (R5): what is transient, when the breaker opens, tier ordering.

No I/O, no clock, no randomness: callers pass `now` and `rand` in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Slots of the model chain, best first: primary (Sonnet) → secondary (Groq 120b) → fallback
# (Haiku) → template. The label is the slot, not the provider, so it means the same everywhere.
Tier = Literal["primary", "secondary", "fallback", "template"]
_TIER_RANK: dict[str, int] = {"primary": 0, "secondary": 1, "fallback": 2, "template": 3}

# Only these are worth retrying; bad output goes straight to the fallback.
_TRANSIENT = frozenset({"rate_limit", "server_unavailable", "timeout"})


def is_transient(kind: str) -> bool:
    return kind in _TRANSIENT


def backoff_delay(attempt: int, rand: float, base: float = 0.5, cap: float = 8.0) -> float:
    """Full-jitter exponential backoff: rand (in [0, 1]) times min(cap, base * 2**attempt)."""
    return rand * min(cap, base * (2 ** min(attempt, 30)))


@dataclass(frozen=True)
class BreakerState:
    failures: int = 0
    opened_at: float | None = None


def breaker_allows(state: BreakerState, now: float, cooldown_s: float) -> bool:
    """Closed → allow. Open → block until the cooldown passes, then allow one probe."""
    return state.opened_at is None or now - state.opened_at >= cooldown_s


def breaker_next(state: BreakerState, failure: str | None, now: float, threshold: int) -> BreakerState:
    """Next state after a call. `failure` is None on success, else the failure kind.

    Only transient failures count: bad output says nothing about provider health.
    """
    if failure is None:
        return BreakerState()
    if not is_transient(failure):
        return state
    failures = state.failures + 1
    if failures >= threshold:
        return BreakerState(failures=failures, opened_at=now)  # also re-opens a failed probe
    return BreakerState(failures=failures, opened_at=state.opened_at)


def worst_tier(current: str | None, new: str | None) -> str | None:
    """The more degraded of two tiers (primary < secondary < fallback < template)."""
    if current is None:
        return new
    if new is None:
        return current
    return new if _TIER_RANK[new] > _TIER_RANK[current] else current


def degrade_verdict(verdict: str, tier: str | None) -> str:
    """A degraded tier never auto-approves: `allow` becomes `needs_approval`. Fail closed."""
    if verdict == "allow" and tier in ("secondary", "fallback", "template"):
        return "needs_approval"
    return verdict
