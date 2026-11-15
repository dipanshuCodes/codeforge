from datetime import datetime, timezone

from codeforge.policy.quota import counts_toward_quota, quota_allows, quota_window_start


def test_under_limit_allows():
    assert quota_allows(used=4, limit=5)


def test_at_limit_refuses():
    assert not quota_allows(used=5, limit=5)


def test_zero_or_negative_limit_refuses():
    assert not quota_allows(used=0, limit=0)
    assert not quota_allows(used=0, limit=-1)


def test_transient_failure_does_not_count():
    assert not counts_toward_quota("cannot_generate")


def test_quota_refusal_does_not_count():
    assert not counts_toward_quota("quota_exceeded")


def test_everything_else_counts_including_in_progress():
    for outcome in ("tests_passed", "tests_failed", "timed_out", "denied", "rejected",
                    "unsupported", None):
        assert counts_toward_quota(outcome)


def test_window_is_the_utc_day():
    now = datetime(2026, 11, 15, 23, 59, tzinfo=timezone.utc)
    assert quota_window_start(now) == datetime(2026, 11, 15, tzinfo=timezone.utc)
