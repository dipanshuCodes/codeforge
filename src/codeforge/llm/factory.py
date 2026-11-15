"""Builds the production caller: Sonnet → Groq 120b → Haiku, each optionally chaotic.

A tier whose API key is missing becomes an UnavailableCaller instead of crashing at startup, so
the chain (and ultimately the template tier) still works. Keys are only tested for presence.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from codeforge.config import Settings
from codeforge.llm.caller import AnthropicCaller, GroqCaller, StructuredCaller, UnavailableCaller
from codeforge.llm.chaos import ChaosCaller
from codeforge.llm.resilient import ResilientCaller


def _has(env: Mapping[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())


def build_caller(
    settings: Settings,
    primary: StructuredCaller | None = None,
    fallback: StructuredCaller | None = None,
    *,
    env: Mapping[str, str] = os.environ,
    make_anthropic: Callable[[str], StructuredCaller] = AnthropicCaller,
    make_groq: Callable[[str], StructuredCaller] = GroqCaller,
) -> ResilientCaller:
    """`primary`/`fallback` can be injected (tests, chaos run) for a two-tier chain; otherwise
    the three production tiers are built from settings and the keys present in `env`.

    Chaos wraps each tier separately (distinct seeds), so later tiers can fail too.
    """
    if primary is not None or fallback is not None:
        if primary is None or fallback is None:
            raise ValueError("inject both primary and fallback, or neither")
        tiers = [primary, fallback]
    else:
        anthropic_ok, groq_ok = _has(env, "ANTHROPIC_API_KEY"), _has(env, "GROQ_API_KEY")
        tiers = [
            make_anthropic(settings.primary_model) if anthropic_ok
            else UnavailableCaller("ANTHROPIC_API_KEY is not set"),
            make_groq(settings.secondary_model) if groq_ok
            else UnavailableCaller("GROQ_API_KEY is not set"),
            make_anthropic(settings.fallback_model) if anthropic_ok
            else UnavailableCaller("ANTHROPIC_API_KEY is not set"),
        ]
    if settings.chaos_rate > 0:
        tiers = [ChaosCaller(t, settings.chaos_rate, settings.chaos_seed + i)
                 for i, t in enumerate(tiers)]
    return ResilientCaller(*tiers)
