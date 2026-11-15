"""Model-call wrapper (R5): retry transient errors, circuit breaker, small-model fallback.

Order per call: primary (jittered retry on transient errors only) → fallback. Bad output is
never retried: it goes straight to the fallback. If both tiers fail it raises
ModelUnavailableError and the graph decides (template tier, or "cannot generate now").
The rules themselves are pure and live in policy/resilience.py.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from codeforge.llm.caller import ModelCallError, ModelOutputError, ModelUnavailableError, StructuredCaller
from codeforge.policy.resilience import (
    BreakerState, backoff_delay, breaker_allows, breaker_next, is_transient,
)

T = TypeVar("T", bound=BaseModel)


class ResilientCaller:
    def __init__(
        self,
        primary: StructuredCaller,
        fallback: StructuredCaller,
        *,
        max_retries: int = 2,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._max_retries = max_retries
        self._threshold = breaker_threshold
        self._cooldown = breaker_cooldown_s
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._clock = clock
        self._breaker = BreakerState()
        self.last_tier: str | None = None  # tier that answered the most recent call

    @staticmethod
    def _kind(exc: ModelCallError) -> str:
        if isinstance(exc, ModelOutputError):
            return "bad_output"
        return getattr(exc, "kind", "other")

    def _try_primary(self, schema: type[T], system: str, user: str) -> T:
        attempt = 0
        while True:
            try:
                result = self._primary.call(schema, system, user)
            except ModelCallError as exc:
                kind = self._kind(exc)
                self._breaker = breaker_next(self._breaker, kind, self._clock(), self._threshold)
                if not is_transient(kind) or attempt >= self._max_retries:
                    raise
                if not breaker_allows(self._breaker, self._clock(), self._cooldown):
                    raise  # breaker just opened: stop retrying a failing provider
                self._sleep(backoff_delay(attempt, self._rng.random()))
                attempt += 1
            else:
                self._breaker = breaker_next(self._breaker, None, self._clock(), self._threshold)
                return result

    def call(self, schema: type[T], system: str, user: str) -> T:
        if breaker_allows(self._breaker, self._clock(), self._cooldown):
            try:
                result = self._try_primary(schema, system, user)
                self.last_tier = "primary"
                return result
            except ModelCallError:
                pass  # fall through to the fallback
        try:
            result = self._fallback.call(schema, system, user)
        except ModelCallError as exc:
            raise ModelUnavailableError("all serving tiers failed", kind=self._kind(exc)) from exc
        self.last_tier = "fallback"
        return result
