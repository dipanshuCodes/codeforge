import pytest

from codeforge.config import Settings
from codeforge.runs.store import RunRecord, RunStore


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "runs.db")


def _store(db: str, user: str) -> RunStore:
    return RunStore(Settings(user_id=user, role="student", db_path=db))


def _record(run_id: str = "r1", **overrides) -> RunRecord:
    base = dict(run_id=run_id, conversation_id="c1", created_at="2026-11-15T10:00:00+00:00",
                request="Write a palindrome checker")
    base.update(overrides)
    return RunRecord(**base)


def test_save_and_get_roundtrip(db):
    store = _store(db, "u-alice")
    rec = _record(kind="python_function", outcome="tests_passed", verdict="needs_approval",
                  reasons=["a", "b"], approved=True, code="c", tests="t", exit_code=0,
                  timed_out=False, output="o", serving_tier="primary", report="rep")
    store.save(rec)
    assert store.get("r1") == rec


def test_other_users_run_looks_missing(db):
    _store(db, "u-alice").save(_record())
    bob = _store(db, "u-bob")
    assert bob.get("r1") is None
    assert bob.get("nope") is None


def test_list_mine_only_own_newest_first(db):
    alice = _store(db, "u-alice")
    alice.save(_record("r1", created_at="2026-11-15T10:00:00+00:00"))
    alice.save(_record("r2", created_at="2026-11-15T11:00:00+00:00"))
    _store(db, "u-bob").save(_record("r3"))
    assert [r.run_id for r in alice.list_mine()] == ["r2", "r1"]


def test_cannot_overwrite_other_users_run(db):
    _store(db, "u-alice").save(_record(outcome="tests_passed"))
    _store(db, "u-bob").save(_record(outcome="denied"))
    assert _store(db, "u-alice").get("r1").outcome == "tests_passed"
    assert _store(db, "u-bob").get("r1") is None


def test_save_updates_own_run(db):
    store = _store(db, "u-alice")
    store.save(_record())
    store.save(_record(outcome="rejected", approved=False))
    got = store.get("r1")
    assert got.outcome == "rejected"
    assert got.approved is False
