"""Builds the production caller: large model → small model fallback, each optionally chaotic."""

from __future__ import annotations

from codeforge.config import Settings
from codeforge.llm.caller import GroqCaller, StructuredCaller
from codeforge.llm.chaos import ChaosCaller
from codeforge.llm.resilient import ResilientCaller


def build_caller(settings: Settings, primary: StructuredCaller | None = None,
                 fallback: StructuredCaller | None = None) -> ResilientCaller:
    """`primary`/`fallback` can be injected (tests, chaos run); default to Groq models.

    Chaos wraps each tier separately, so the fallback can fail too.
    """
    primary = primary or GroqCaller(settings.large_model)
    fallback = fallback or GroqCaller(settings.small_model)
    if settings.chaos_rate > 0:
        primary = ChaosCaller(primary, settings.chaos_rate, settings.chaos_seed)
        fallback = ChaosCaller(fallback, settings.chaos_rate, settings.chaos_seed + 1)
    return ResilientCaller(primary, fallback)


def build_summary_caller(settings: Settings, inner: StructuredCaller | None = None) -> StructuredCaller:
    """Small model for the advisory Handoff summary (R3). No retry or fallback: on any failure
    the summary is simply absent. Chaos applies here too."""
    caller = inner or GroqCaller(settings.small_model)
    if settings.chaos_rate > 0:
        caller = ChaosCaller(caller, settings.chaos_rate, settings.chaos_seed + 2)
    return caller
