import pytest

from codeforge.policy.resilience import (
    BreakerState, backoff_delay, breaker_allows, breaker_next, degrade_verdict, is_transient,
    worst_tier,
)


@pytest.mark.parametrize("kind", ["rate_limit", "server_unavailable", "timeout"])
def test_transient_kinds_are_retried(kind):
    assert is_transient(kind)


@pytest.mark.parametrize("kind", ["bad_output", "other", "auth"])
def test_bad_output_and_unknown_are_not_retried(kind):
    assert not is_transient(kind)


def test_backoff_is_jittered_exponential_and_capped():
    assert backoff_delay(0, rand=0.0) == 0.0
    assert backoff_delay(0, rand=1.0, base=0.5) == 0.5
    assert backoff_delay(2, rand=1.0, base=0.5) == 2.0
    assert backoff_delay(20, rand=1.0, base=0.5, cap=8.0) == 8.0
    assert backoff_delay(2, rand=0.5, base=0.5) == 1.0


def test_breaker_stays_closed_below_threshold():
    s = BreakerState()
    for _ in range(2):
        s = breaker_next(s, "timeout", now=0.0, threshold=3)
    assert breaker_allows(s, now=1.0, cooldown_s=30)


def test_breaker_opens_at_threshold_and_blocks_until_cooldown():
    s = BreakerState()
    for _ in range(3):
        s = breaker_next(s, "rate_limit", now=10.0, threshold=3)
    assert not breaker_allows(s, now=20.0, cooldown_s=30)
    assert breaker_allows(s, now=40.0, cooldown_s=30)  # half-open probe


def test_success_closes_the_breaker():
    s = BreakerState(failures=3, opened_at=10.0)
    s = breaker_next(s, None, now=50.0, threshold=3)
    assert s == BreakerState()


def test_failed_probe_reopens_with_new_clock():
    s = BreakerState(failures=3, opened_at=10.0)
    s = breaker_next(s, "server_unavailable", now=50.0, threshold=3)
    assert s.opened_at == 50.0
    assert not breaker_allows(s, now=60.0, cooldown_s=30)


def test_bad_output_does_not_count_against_the_provider():
    s = BreakerState()
    for _ in range(10):
        s = breaker_next(s, "bad_output", now=0.0, threshold=3)
    assert s == BreakerState()


def test_worst_tier_orders_primary_fallback_template():
    assert worst_tier(None, "primary") == "primary"
    assert worst_tier("primary", "fallback") == "fallback"
    assert worst_tier("template", "primary") == "template"


@pytest.mark.parametrize("tier", ["fallback", "template"])
def test_degraded_tier_never_auto_allows(tier):
    assert degrade_verdict("allow", tier) == "needs_approval"
    assert degrade_verdict("deny", tier) == "deny"
    assert degrade_verdict("needs_approval", tier) == "needs_approval"


def test_primary_tier_keeps_the_verdict():
    assert degrade_verdict("allow", "primary") == "allow"
    assert degrade_verdict("allow", None) == "allow"
