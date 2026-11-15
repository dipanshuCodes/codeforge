"""Structured model calls. Agents depend on `StructuredCaller`, never on a provider.

L1: one call, no retry or fallback (R5 wraps this). Failures are typed so the graph can
tell bad output from an unavailable provider.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ModelCallError(Exception):
    """A model call did not produce a usable answer."""


class ModelOutputError(ModelCallError):
    """The model answered, but the output was unparsable or failed validation."""


class ModelUnavailableError(ModelCallError):
    """The provider failed (rate limit, server error, timeout, network).

    `kind` is one of rate_limit / server_unavailable / timeout / other; R5 retries only the
    transient ones (see policy/resilience.py).
    """

    def __init__(self, message: str = "", kind: str = "other") -> None:
        super().__init__(message)
        self.kind = kind


def classify_failure(exc: BaseException) -> str:
    """Map a provider exception to a failure kind, from its status code or type name."""
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    if status == 429 or "ratelimit" in name:
        return "rate_limit"
    if status in (500, 502, 503, 504, 529) or "internalserver" in name or "serviceunavailable" in name:
        return "server_unavailable"
    if "timeout" in name or isinstance(exc, TimeoutError):
        return "timeout"
    return "other"


class StructuredCaller(Protocol):
    def call(self, schema: type[T], system: str, user: str) -> T: ...


class GroqCaller:
    """Calls a Groq model with structured output. The key is read by langchain-groq."""

    def __init__(self, model: str) -> None:
        from langchain_groq import ChatGroq  # imported lazily so tests need no key

        self._llm = ChatGroq(model=model, temperature=0)

    def call(self, schema: type[T], system: str, user: str) -> T:
        structured = self._llm.with_structured_output(schema, include_raw=True)
        try:
            result: dict[str, Any] = structured.invoke([("system", system), ("user", user)])
        except (ValidationError, ValueError) as exc:
            raise ModelOutputError(type(exc).__name__) from exc
        except Exception as exc:  # provider/network errors; R5 retries the transient ones
            raise ModelUnavailableError(type(exc).__name__, kind=classify_failure(exc)) from exc
        parsed = result.get("parsed")
        if result.get("parsing_error") is not None or not isinstance(parsed, schema):
            raise ModelOutputError("structured output failed to parse")
        return parsed


class AnthropicCaller:
    """Calls a Claude model with structured output. The key is read by langchain-anthropic.

    The client's own retries are off (`max_retries=0`): only ResilientCaller retries, so the
    breaker counts real failures.
    """

    def __init__(self, model: str, timeout_s: float = 60.0) -> None:
        from langchain_anthropic import ChatAnthropic  # lazy: tests need no key

        # No `temperature`: Claude 5.5 models reject non-default values (400), which would
        # silently drop every Run to the template tier.
        self._llm = ChatAnthropic(model=model, max_retries=0, timeout=timeout_s)

    def call(self, schema: type[T], system: str, user: str) -> T:
        # json_schema, not the default forced tool call: Sonnet 5.5 doesn't support forcing a tool.
        structured = self._llm.with_structured_output(
            schema, include_raw=True, method="json_schema"
        )
        try:
            result: dict[str, Any] = structured.invoke([("system", system), ("user", user)])
        except (ValidationError, ValueError) as exc:
            raise ModelOutputError(type(exc).__name__) from exc
        except Exception as exc:
            raise ModelUnavailableError(type(exc).__name__, kind=classify_failure(exc)) from exc
        parsed = result.get("parsed")
        if result.get("parsing_error") is not None or not isinstance(parsed, schema):
            raise ModelOutputError("structured output failed to parse")
        return parsed


class UnavailableCaller:
    """Placeholder for a tier whose API key is missing. Fails at once with a non-transient kind,
    so it is never retried and never trips the breaker; the chain moves to the next tier."""

    def __init__(self, reason: str = "no API key") -> None:
        self._reason = reason

    def call(self, schema: type[T], system: str, user: str) -> T:
        raise ModelUnavailableError(self._reason, kind="other")


class FakeCaller:
    """Offline caller for tests: returns or raises a canned value per schema."""

    def __init__(self, responses: dict[type, BaseModel | Exception]) -> None:
        self._responses = responses
        self.calls: list[tuple[type, str, str]] = []

    def call(self, schema: type[T], system: str, user: str) -> T:
        self.calls.append((schema, system, user))
        if schema not in self._responses:
            raise ModelOutputError(f"no canned response for {schema.__name__}")
        value = self._responses[schema]
        if isinstance(value, Exception):
            raise value
        return value  # type: ignore[return-value]
