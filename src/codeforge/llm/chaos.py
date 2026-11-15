"""Chaos switch (R5): fails a seeded share of model calls with a mix of realistic errors."""

from __future__ import annotations

import random
from typing import TypeVar

from pydantic import BaseModel

from codeforge.llm.caller import ModelOutputError, ModelUnavailableError, StructuredCaller

T = TypeVar("T", bound=BaseModel)

_FAILURES = ("rate_limit", "server_unavailable", "timeout", "bad_output")


class ChaosCaller:
    def __init__(self, inner: StructuredCaller, rate: float, seed: int) -> None:
        self._inner = inner
        self._rate = rate
        self._rng = random.Random(seed)  # fixed seed: the chaos run is reproducible

    def call(self, schema: type[T], system: str, user: str) -> T:
        if self._rng.random() < self._rate:
            kind = self._rng.choice(_FAILURES)
            if kind == "bad_output":
                raise ModelOutputError("chaos: injected bad output")
            raise ModelUnavailableError(f"chaos: injected {kind}", kind=kind)
        return self._inner.call(schema, system, user)
