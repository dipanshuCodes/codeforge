"""Handoff note: template summary line always present, AI summary re-masked, last failing test."""
from codeforge.agents.handoff import summarize_handoff
from codeforge.agents.schemas import HandoffSummary
from codeforge.llm.caller import FakeCaller
from codeforge.reporting.handoff import HandoffNote, last_failing_test

OUTPUT = (
    "F.\n=================================== FAILURES ===================================\n"
    "...\n=========================== short test summary info ============================\n"
    "FAILED test_solution.py::test_empty - AssertionError: assert None == 0\n"
    "FAILED test_solution.py::test_other - assert 1 == 2\n"
    "1 failed, 1 passed in 0.02s\n"
)


def test_last_failing_test_is_the_first_failed_line():
    assert last_failing_test(OUTPUT) == "test_solution.py::test_empty"


def test_no_failing_test():
    assert last_failing_test("2 passed in 0.01s\n") is None
    assert last_failing_test(None) is None


def note(**kw):
    base = dict(priority="P1", sla_hours=1, reason="asked for a human; angry or urgent",
                request="THIS IS NOT WORKING!!! get me a human [SECRET]", attempts=0)
    base.update(kw)
    return HandoffNote(**base)


def test_summary_line_is_template_and_always_present():
    n = note()
    assert n.summary_line() == ("P1 (SLA 1 h): asked for a human; angry or urgent. "
                                "0 Executions; no failing test.")
    text = n.render()
    assert text.splitlines()[0] == n.summary_line()
    assert "Request: THIS IS NOT WORKING!!! get me a human [SECRET]" in text
    assert "AI summary" not in text  # absent when the small model gave none


def test_render_includes_attempts_failing_test_and_ai_summary():
    text = note(priority="P3", sla_hours=24, reason="2 policy denials", attempts=2,
                last_failing_test="test_solution.py::test_empty",
                ai_summary="Student is stuck.").render()
    assert "2 Executions; last failing test: test_solution.py::test_empty." in text
    assert "AI summary (advisory): Student is stuck." in text


def test_ai_summary_is_masked_again():
    # The small model could echo something that looks like a key; it is masked before saving.
    n = note(ai_summary="Key gsk_abcdefghijklmnopqrstuvwxyz0123 and Aadhaar 2345 6789 0123.")
    assert "gsk_" not in n.render() and "2345 6789 0123" not in n.render()
    assert "[SECRET]" in n.ai_summary


def test_summarize_handoff_uses_masked_fields():
    caller = FakeCaller({HandoffSummary: HandoffSummary(summary="Wants a person.")})
    n = note()
    assert summarize_handoff(caller, n).summary == "Wants a person."
    _schema, _system, user = caller.calls[0]
    assert n.request in user and n.summary_line() in user
