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
    """Ordered chain of callers: first is `primary`, last is `fallback`, any between are `secondary`.

    Every tier but the last gets jittered retries on transient errors and its own breaker, so one
    provider being down never blocks the others. The last tier gets a single try.
    """

    def __init__(
        self,
        *callers: StructuredCaller,
        max_retries: int = 2,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if len(callers) < 2:
            raise ValueError("ResilientCaller needs at least two callers")
        self._callers = list(callers)
        n = len(callers)
        self._names = ["primary"] + ["secondary"] * (n - 2) + ["fallback"]
        self._max_retries = max_retries
        self._threshold = breaker_threshold
        self._cooldown = breaker_cooldown_s
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._clock = clock
        self._breakers = [BreakerState() for _ in callers]
        self.last_tier: str | None = None  # tier that answered the most recent call

    @staticmethod
    def _kind(exc: ModelCallError) -> str:
        if isinstance(exc, ModelOutputError):
            return "bad_output"
        return getattr(exc, "kind", "other")

    def _try(self, i: int, schema: type[T], system: str, user: str, retries: int) -> T:
        attempt = 0
        while True:
            try:
                result = self._callers[i].call(schema, system, user)
            except ModelCallError as exc:
                kind = self._kind(exc)
                self._breakers[i] = breaker_next(self._breakers[i], kind, self._clock(),
                                                 self._threshold)
                if not is_transient(kind) or attempt >= retries:
                    raise
                if not breaker_allows(self._breakers[i], self._clock(), self._cooldown):
                    raise  # breaker just opened: stop retrying a failing provider
                self._sleep(backoff_delay(attempt, self._rng.random()))
                attempt += 1
            else:
                self._breakers[i] = breaker_next(self._breakers[i], None, self._clock(),
                                                 self._threshold)
                return result

    def call(self, schema: type[T], system: str, user: str) -> T:
        last_exc: ModelCallError | None = None
        last = len(self._callers) - 1
        for i in range(len(self._callers)):
            if not breaker_allows(self._breakers[i], self._clock(), self._cooldown):
                continue
            try:
                result = self._try(i, schema, system, user, 0 if i == last else self._max_retries)
            except ModelCallError as exc:
                last_exc = exc
                continue
            self.last_tier = self._names[i]
            return result
        raise ModelUnavailableError(
            "all serving tiers failed", kind=self._kind(last_exc) if last_exc else "other"
        ) from last_exc
