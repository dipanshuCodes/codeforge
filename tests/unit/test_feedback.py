"""Feedback flywheel (R6): /bad stores Feedback for the config User's own Run; promote writes a
draft Golden case. Fake values only."""

import json

from codeforge.config import Settings
from codeforge.runs.feedback import draft_golden_case
from codeforge.runs.store import RunRecord, RunStore

FAKE_EMAIL = "student.one@example.com"


def _store(tmp_path, user="u-alice"):
    return RunStore(Settings(user_id=user, role="student", db_path=str(tmp_path / "r.db")))


def _run(store, run_id="run-1", **kw):
    record = RunRecord(run_id=run_id, conversation_id="c1", created_at="2026-11-15T00:00:00+00:00",
                       request="Write is_even(n)", kind="python_function", outcome="tests_failed",
                       code="def is_even(n):\n    return n % 2 == 1\n",
                       tests="from solution import is_even\n\ndef test_it():\n    assert is_even(2)\n",
                       **kw)
    store.save(record)
    return record


def test_feedback_on_own_run_is_stored_masked(tmp_path):
    store = _store(tmp_path)
    _run(store)
    fid = store.add_feedback("run-1", f"wrong answer, mail {FAKE_EMAIL}")
    fb = store.get_feedback(fid)
    assert fb.run_id == "run-1" and fb.reason == "wrong answer, mail [EMAIL]"
    assert FAKE_EMAIL.encode() not in (tmp_path / "r.db").read_bytes()


def test_feedback_on_missing_or_foreign_run_is_refused_the_same_way(tmp_path):
    _run(_store(tmp_path, "u-bob"), run_id="bobs-run")
    alice = _store(tmp_path)
    assert alice.add_feedback("bobs-run", "x") is None
    assert alice.add_feedback("no-such-run", "x") is None


def test_feedback_is_scoped_to_the_config_user(tmp_path):
    alice = _store(tmp_path)
    _run(alice)
    fid = alice.add_feedback("run-1", "")
    assert _store(tmp_path, "u-bob").get_feedback(fid) is None
    assert _store(tmp_path, "u-bob").get_feedback("missing") is None


def test_draft_golden_case_is_runnable_but_needs_a_human_expectation(tmp_path):
    store = _store(tmp_path)
    run = _run(store)
    fb = store.get_feedback(store.add_feedback("run-1", "is_even is backwards"))
    case = draft_golden_case(fb, run)
    assert case["draft"] is True and case["check"] == "graph"
    assert case["id"].startswith("F-")
    assert case["graph"]["requests"] == ["Write is_even(n)"]
    model = case["graph"]["model"]
    assert model["code"] == run.code and model["tests"] == run.tests
    assert model["requirements"]["function_name"] == "is_even"
    assert case["source"] == {"feedback_id": fb.feedback_id, "run_id": "run-1",
                              "reason": "is_even is backwards", "observed_outcome": "tests_failed"}
    assert "TODO" in json.dumps(case["expect"])


def test_promote_command_writes_the_draft(tmp_path, monkeypatch, capsys):
    from codeforge.ui.console import main

    db = tmp_path / "r.db"
    monkeypatch.setenv("CODEFORGE_USER_ID", "u-alice")
    monkeypatch.setenv("CODEFORGE_ROLE", "student")
    monkeypatch.setenv("CODEFORGE_DB_PATH", str(db))
    monkeypatch.chdir(tmp_path)
    store = _store(tmp_path)
    _run(store)
    fid = store.add_feedback("run-1", "backwards")
    main(["feedback", "promote", fid])
    drafts = list((tmp_path / "evals" / "drafts").glob("*.json"))
    assert len(drafts) == 1
    assert json.loads(drafts[0].read_text())["source"]["feedback_id"] == fid
    assert str(drafts[0].name) in capsys.readouterr().out


def test_promote_unknown_feedback_exits_1(tmp_path, monkeypatch, capsys):
    import pytest

    from codeforge.ui.console import main

    monkeypatch.setenv("CODEFORGE_USER_ID", "u-alice")
    monkeypatch.setenv("CODEFORGE_ROLE", "student")
    monkeypatch.setenv("CODEFORGE_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["feedback", "promote", "nope"])
    assert exc.value.code == 1
    assert not (tmp_path / "evals").exists()
