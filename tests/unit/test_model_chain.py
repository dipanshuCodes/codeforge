"""Model chain: Sonnet -> Groq 120b -> Haiku, missing keys, failure classification."""
import pytest

from codeforge.agents.schemas import RouterOutput
from codeforge.config import Settings
from codeforge.llm.caller import (
    ModelUnavailableError, UnavailableCaller, classify_failure,
)
from codeforge.llm.factory import build_caller
from codeforge.llm.resilient import ResilientCaller


class _Status(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.mark.parametrize("status,kind", [
    (429, "rate_limit"), (500, "server_unavailable"), (503, "server_unavailable"),
    (529, "server_unavailable"), (401, "other"), (400, "other"),
])
def test_classify_failure_by_status(status, kind):
    assert classify_failure(_Status(status)) == kind


def _settings():
    return Settings(user_id="u", role="student")


class _Marker:
    def __init__(self, name):
        self.name = name

    def call(self, schema, system, user):
        return RouterOutput(kind="python_function")


def _chain(rc):
    return [type(c).__name__ if not isinstance(c, _Marker) else c.name for c in rc._callers]


def test_all_keys_present_builds_sonnet_groq_haiku():
    built = []
    rc = build_caller(_settings(), env={"ANTHROPIC_API_KEY": "x", "GROQ_API_KEY": "y"},
                      make_anthropic=lambda m: built.append(m) or _Marker(m),
                      make_groq=lambda m: built.append(m) or _Marker(m))
    assert built == ["claude-sonnet-5-5", "openai/gpt-oss-120b", "claude-haiku-5-5"]
    assert _chain(rc) == built


def test_missing_anthropic_key_leaves_unavailable_slots_not_a_crash():
    rc = build_caller(_settings(), env={"GROQ_API_KEY": "y"},
                      make_anthropic=lambda m: _Marker(m), make_groq=lambda m: _Marker(m))
    assert _chain(rc) == ["UnavailableCaller", "openai/gpt-oss-120b", "UnavailableCaller"]
    rc.call(RouterOutput, "s", "u")
    assert rc.last_tier == "secondary"  # labelled by slot, so it never auto-approves


def test_no_keys_every_call_is_unavailable_so_the_graph_uses_templates():
    rc = build_caller(_settings(), env={},
                      make_anthropic=lambda m: _Marker(m), make_groq=lambda m: _Marker(m))
    assert all(isinstance(c, UnavailableCaller) for c in rc._callers)
    with pytest.raises(ModelUnavailableError):
        rc.call(RouterOutput, "s", "u")


def test_blank_key_counts_as_missing():
    rc = build_caller(_settings(), env={"ANTHROPIC_API_KEY": "  ", "GROQ_API_KEY": ""},
                      make_anthropic=lambda m: _Marker(m), make_groq=lambda m: _Marker(m))
    assert all(isinstance(c, UnavailableCaller) for c in rc._callers)


def test_injected_callers_are_used_as_is():
    a, b = _Marker("a"), _Marker("b")
    rc = build_caller(_settings(), a, b)
    assert isinstance(rc, ResilientCaller) and _chain(rc) == ["a", "b"]
