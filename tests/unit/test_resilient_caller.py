import random

import pytest

from codeforge.agents.schemas import RouterOutput
from codeforge.llm.caller import ModelOutputError, ModelUnavailableError
from codeforge.llm.chaos import ChaosCaller
from codeforge.llm.resilient import ResilientCaller

OK = RouterOutput(kind="python_function")


class Scripted:
    """Returns/raises the next scripted item per call."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def call(self, schema, system, user):
        self.calls += 1
        item = self.script.pop(0) if self.script else OK
        if isinstance(item, Exception):
            raise item
        return item


def _rc(primary, fallback=None, now=lambda: 0.0, **kw):
    sleeps = []
    rc = ResilientCaller(primary, fallback or Scripted(), sleep=sleeps.append,
                         rng=random.Random(1), clock=now, **kw)
    rc.sleeps = sleeps
    return rc


def _err(kind):
    return ModelUnavailableError(kind, kind=kind)


def test_success_uses_primary_tier():
    rc = _rc(Scripted(OK))
    assert rc.call(RouterOutput, "s", "u") == OK
    assert rc.last_tier == "primary"


def test_transient_error_is_retried_with_jitter_then_succeeds():
    primary = Scripted(_err("rate_limit"), _err("timeout"), OK)
    rc = _rc(primary, max_retries=2)
    rc.call(RouterOutput, "s", "u")
    assert primary.calls == 3 and len(rc.sleeps) == 2 and rc.last_tier == "primary"


def test_bad_output_skips_retry_and_goes_to_fallback():
    primary, fallback = Scripted(ModelOutputError("bad")), Scripted(OK)
    rc = _rc(primary, fallback)
    rc.call(RouterOutput, "s", "u")
    assert primary.calls == 1 and fallback.calls == 1 and rc.last_tier == "fallback"
    assert rc.sleeps == []


def test_non_transient_unavailable_is_not_retried():
    primary = Scripted(_err("other"))
    rc = _rc(primary, Scripted(OK))
    rc.call(RouterOutput, "s", "u")
    assert primary.calls == 1 and rc.last_tier == "fallback"


def test_exhausted_retries_fall_back():
    primary = Scripted(*[_err("server_unavailable")] * 5)
    rc = _rc(primary, Scripted(OK), max_retries=2)
    rc.call(RouterOutput, "s", "u")
    assert primary.calls == 3 and rc.last_tier == "fallback"


def test_both_tiers_failing_raises_unavailable():
    rc = _rc(Scripted(ModelOutputError("x")), Scripted(ModelOutputError("y")))
    with pytest.raises(ModelUnavailableError):
        rc.call(RouterOutput, "s", "u")


def test_open_breaker_skips_primary():
    primary = Scripted(*[_err("timeout")] * 20)
    rc = _rc(primary, Scripted(), max_retries=0, breaker_threshold=2, breaker_cooldown_s=30)
    rc.call(RouterOutput, "s", "u")
    rc.call(RouterOutput, "s", "u")  # breaker opens after this failure
    before = primary.calls
    rc.call(RouterOutput, "s", "u")
    assert primary.calls == before and rc.last_tier == "fallback"


def test_breaker_probes_primary_after_cooldown():
    t = [0.0]
    primary = Scripted(_err("timeout"), _err("timeout"), OK)
    rc = _rc(primary, Scripted(), now=lambda: t[0], max_retries=0, breaker_threshold=2,
             breaker_cooldown_s=30)
    rc.call(RouterOutput, "s", "u"); rc.call(RouterOutput, "s", "u")
    t[0] = 31.0
    rc.call(RouterOutput, "s", "u")
    assert rc.last_tier == "primary"


def test_chaos_is_deterministic_for_a_seed():
    def run(seed):
        c = ChaosCaller(Scripted(*[OK] * 200), rate=0.6, seed=seed)
        out = []
        for _ in range(100):
            try:
                c.call(RouterOutput, "s", "u")
                out.append("ok")
            except Exception as exc:  # noqa: BLE001
                out.append(getattr(exc, "kind", type(exc).__name__))
        return out

    assert run(7) == run(7)
    assert run(7) != run(8)


def test_chaos_fails_about_the_configured_share_with_a_mix_of_kinds():
    c = ChaosCaller(Scripted(*[OK] * 1000), rate=0.6, seed=3)
    kinds = []
    for _ in range(1000):
        try:
            c.call(RouterOutput, "s", "u")
        except ModelOutputError:
            kinds.append("bad_output")
        except ModelUnavailableError as exc:
            kinds.append(exc.kind)
    assert 540 <= len(kinds) <= 660
    assert set(kinds) == {"rate_limit", "server_unavailable", "timeout", "bad_output"}


def test_chaos_rate_zero_never_fails():
    c = ChaosCaller(Scripted(*[OK] * 50), rate=0.0, seed=1)
    for _ in range(50):
        c.call(RouterOutput, "s", "u")


def test_three_tiers_are_named_primary_secondary_fallback():
    a, b, c = Scripted(_err("other")), Scripted(_err("other")), Scripted(OK)
    rc = ResilientCaller(a, b, c, sleep=lambda _s: None)
    rc.call(RouterOutput, "s", "u")
    assert rc.last_tier == "fallback" and (a.calls, b.calls, c.calls) == (1, 1, 1)
    rc2 = ResilientCaller(Scripted(_err("other")), Scripted(OK), Scripted(), sleep=lambda _s: None)
    rc2.call(RouterOutput, "s", "u")
    assert rc2.last_tier == "secondary"


def test_breakers_are_per_tier():
    first = Scripted(*[_err("timeout")] * 20)
    second = Scripted(*[OK] * 20)
    rc = ResilientCaller(first, second, Scripted(), max_retries=0, breaker_threshold=2,
                         breaker_cooldown_s=30, sleep=lambda _s: None, clock=lambda: 0.0)
    for _ in range(4):
        rc.call(RouterOutput, "s", "u")
    # tier 1's breaker is open (skipped after 2 failures); tier 2's stayed closed and answered
    assert first.calls == 2 and second.calls == 4 and rc.last_tier == "secondary"


def test_all_three_failing_raises_unavailable():
    rc = ResilientCaller(*[Scripted(_err("other")) for _ in range(3)], sleep=lambda _s: None)
    with pytest.raises(ModelUnavailableError):
        rc.call(RouterOutput, "s", "u")


def test_unavailable_caller_fails_instantly_and_is_not_transient():
    from codeforge.llm.caller import UnavailableCaller
    from codeforge.policy.resilience import is_transient

    with pytest.raises(ModelUnavailableError) as info:
        UnavailableCaller("no key").call(RouterOutput, "s", "u")
    assert not is_transient(info.value.kind)
