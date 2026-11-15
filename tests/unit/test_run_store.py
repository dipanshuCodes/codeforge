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


# --- Request key and Execution key (R2) -------------------------------------------------

def test_find_final_run_only_final_and_own(db):
    alice = _store(db, "u-alice")
    alice.save(_record("r1", request_key="k", outcome="cannot_generate"))  # Transient failure
    alice.save(_record("r2", request_key="k"))                            # still in progress
    assert alice.find_final_run("k") is None
    alice.save(_record("r3", request_key="k", outcome="tests_failed"))
    assert alice.find_final_run("k").run_id == "r3"
    assert _store(db, "u-bob").find_final_run("k") is None


def test_find_final_run_ignores_duplicates_of_it(db):
    alice = _store(db, "u-alice")
    alice.save(_record("r1", request_key="k", outcome="tests_passed"))
    alice.save(_record("r2", request_key="k", outcome="tests_passed", duplicate_of="r1",
                       created_at="2026-11-15T11:00:00+00:00"))
    assert alice.find_final_run("k").run_id == "r1"


def test_executions_are_stored_per_user(db):
    alice = _store(db, "u-alice")
    assert alice.get_execution("e") is None
    alice.save_execution("e", {"exit_code": 0, "timed_out": False, "output": "1 passed"})
    assert alice.get_execution("e") == {"exit_code": 0, "timed_out": False, "output": "1 passed"}
    assert _store(db, "u-bob").get_execution("e") is None


def test_old_database_gains_new_columns(db):
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
                 "conversation_id TEXT, created_at TEXT, request TEXT)")
    conn.commit(); conn.close()
    store = _store(db, "u-alice")
    store.save(_record("r1", request_key="k", outcome="denied"))
    assert store.find_final_run("k").run_id == "r1"


def test_ticket_with_priority_sla_and_handoff_note(db):
    store = _store(db, "u-alice")
    tid = store.add_ticket("r1", "angry", None, "masked [SECRET]",
                           priority="P2", sla_hours=4, handoff_note="P2 · angry")
    (t,) = store.list_tickets()
    assert (t.ticket_id, t.priority, t.sla_hours, t.handoff_note) == (tid, "P2", 4, "P2 · angry")


def test_outage_ticket_still_works_without_priority(db):
    store = _store(db, "u-alice")
    store.add_ticket("r1", "model outage, no template match", "template", "req")
    (t,) = store.list_tickets()
    assert t.priority is None and t.sla_hours is None and t.handoff_note is None
    assert t.serving_tier == "template"


def test_tickets_are_scoped_to_the_config_user(db):
    _store(db, "u-bob").add_ticket("r9", "angry", None, "req", priority="P2", sla_hours=4)
    assert _store(db, "u-alice").list_tickets() == []


def test_old_tickets_table_gains_new_columns(db):
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
                 "run_id TEXT NOT NULL, created_at TEXT NOT NULL, reason TEXT NOT NULL, "
                 "serving_tier TEXT, request TEXT NOT NULL)")
    conn.commit(); conn.close()
    store = _store(db, "u-alice")
    store.add_ticket("r1", "angry", None, "req", priority="P1", sla_hours=1, handoff_note="n")
    assert store.list_tickets()[0].priority == "P1"
