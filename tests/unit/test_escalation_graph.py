"""R3 in the graph: Tickets, P1 short-cut, signals across a Conversation, nothing secret saved."""
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import (
    CodeOutput, HandoffSummary, Param, Requirements, RouterOutput, TestsOutput, TriageOutput,
)
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller, ModelUnavailableError
from codeforge.runs.store import RunStore

FAKE_KEY = "gsk_" + "FAKEfake0123456789abcdef"
FAKE_AADHAAR = "2345 6789 0123"
STUDENT_C = f"THIS IS NOT WORKING!!! get me a human. key {FAKE_KEY} aadhaar {FAKE_AADHAAR}"

CODE = "def is_palindrome(s):\n    return s == s[::-1]\n"
TESTS = "from solution import is_palindrome\n\ndef test_a():\n    assert is_palindrome('aba')\n"
DENIED_CODE = "import os\n\ndef is_palindrome(s):\n    os.system('rm -rf ~')\n    return True\n"
REQ = Requirements(function_name="is_palindrome", description="d",
                   params=[Param(name="s", type="str")], returns="bool", edge_cases=[])


def tri(sentiment="calm", urgency="low", wants_human=False):
    return TriageOutput(language="en", sentiment=sentiment, urgency=urgency,
                        wants_human=wants_human)


class TurnCaller(FakeCaller):
    """FakeCaller whose Triage answer changes per turn (one entry per Request)."""

    def __init__(self, triages, code=CODE):
        super().__init__({RouterOutput: RouterOutput(kind="python_function"), Requirements: REQ,
                          CodeOutput: CodeOutput(code=code), TestsOutput: TestsOutput(tests=TESTS)})
        self._triages = list(triages)

    def call(self, schema, system, user):
        if schema is TriageOutput:
            self.calls.append((schema, system, user))
            value = self._triages.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return super().call(schema, system, user)


@pytest.fixture
def parts(tmp_path):
    settings = Settings(user_id="u-carol", role="student", db_path=str(tmp_path / "r.db"),
                        sandbox_timeout_s=5)
    return settings, RunStore(settings)


def _graph(parts, caller, summary_caller=None):
    settings, store = parts
    return build_graph(settings, caller, store, checkpointer=MemorySaver(),
                       summary_caller=summary_caller)


def _turn(graph, text, thread="conv-c"):
    cfg = {"configurable": {"thread_id": thread}}
    result = graph.invoke({"raw_text": text}, cfg)
    if "__interrupt__" in result:
        result = graph.invoke(Command(resume="approve"), cfg)
    return result


def test_student_c_opens_p1_ticket_without_generation_or_secrets(parts):
    settings, store = parts
    caller = TurnCaller([tri("angry", "high", True)])
    summary = FakeCaller({HandoffSummary: HandoffSummary(summary=f"Wants a human; key {FAKE_KEY}")})
    result = _turn(_graph(parts, caller, summary), STUDENT_C)

    assert result["outcome"] == "escalated"
    assert [c[0] for c in caller.calls] == [TriageOutput]  # no router, codegen or testgen
    assert result.get("code") is None
    (ticket,) = store.list_tickets()
    assert ticket.priority == "P1" and ticket.sla_hours == 1
    assert ticket.ticket_id[:8] in result["report"] and "P1" in result["report"]
    assert "HANDED TO A HUMAN" in result["report"]
    assert ticket.handoff_note.startswith("P1 (SLA 1 h)")
    assert "AI summary (advisory): Wants a human; key [SECRET]" in ticket.handoff_note
    assert "[SECRET]" in ticket.request and "[AADHAAR]" in ticket.request
    # Neither the key nor the Aadhaar number is anywhere in the SQLite file.
    raw = Path(settings.db_path).read_bytes()
    assert FAKE_KEY.encode() not in raw and FAKE_AADHAAR.encode() not in raw
    assert b"23456789" not in raw.replace(b" ", b"")


def test_triage_sees_only_the_masked_request(parts):
    caller = TurnCaller([tri("angry", "high", True)])
    _turn(_graph(parts, caller), STUDENT_C)
    _schema, system, user = caller.calls[0]
    assert FAKE_KEY not in system + user and FAKE_AADHAAR not in system + user


def test_calm_request_opens_no_ticket(parts):
    _, store = parts
    result = _turn(_graph(parts, TurnCaller([tri()])), "Write a palindrome checker")
    assert result["outcome"] == "tests_passed"
    assert store.list_tickets() == []
    assert "Ticket" not in result["report"]


def test_two_mildly_unhappy_turns_escalate_though_one_does_not(parts):
    _, store = parts
    g = _graph(parts, TurnCaller([tri("mildly_unhappy"), tri("mildly_unhappy")]))
    first = _turn(g, "ugh, write a palindrome checker")
    assert store.list_tickets() == [] and first["outcome"] == "tests_passed"
    second = _turn(g, "still annoyed, write a palindrome checker again")
    (ticket,) = store.list_tickets()
    assert ticket.priority == "P3" and ticket.sla_hours == 24
    assert second["outcome"] == "tests_passed"  # P3 continues with generation
    assert "P3" in second["report"]


def test_unhappy_turns_do_not_leak_across_conversations(parts):
    _, store = parts
    g = _graph(parts, TurnCaller([tri("mildly_unhappy"), tri("mildly_unhappy")]))
    _turn(g, "ugh, write a palindrome checker", thread="a")
    _turn(g, "meh, write a palindrome checker", thread="b")
    assert store.list_tickets() == []


def test_p2_opens_a_ticket_and_continues(parts):
    _, store = parts
    result = _turn(_graph(parts, TurnCaller([tri("angry")])), "WRITE A PALINDROME CHECKER")
    (ticket,) = store.list_tickets()
    assert ticket.priority == "P2"
    assert result["outcome"] == "tests_passed" and "P2" in result["report"]


def test_one_ticket_per_conversation_unless_stricter(parts):
    _, store = parts
    g = _graph(parts, TurnCaller([tri(wants_human=True), tri(wants_human=True),
                                  tri("angry", "high", True)]))
    _turn(g, "can a person check this palindrome checker")
    _turn(g, "a person please, palindrome checker")
    assert [t.priority for t in store.list_tickets()] == ["P2"]
    third = _turn(g, "NOW. A HUMAN.")
    assert [t.priority for t in store.list_tickets()] == ["P2", "P1"]
    assert third["outcome"] == "escalated"


def test_second_policy_denial_escalates_in_the_same_run(parts):
    _, store = parts
    g = _graph(parts, TurnCaller([tri(), tri()], code=DENIED_CODE))
    assert _turn(g, "palindrome checker one")["outcome"] == "denied"
    assert store.list_tickets() == []
    second = _turn(g, "palindrome checker two")
    assert second["outcome"] == "denied"
    (ticket,) = store.list_tickets()
    assert ticket.priority == "P3" and "2 policy denials" in ticket.handoff_note
    assert "P3" in second["report"]


def test_triage_failure_falls_back_to_calm_and_the_run_continues(parts):
    _, store = parts
    caller = TurnCaller([ModelUnavailableError("down", kind="server_unavailable")])
    result = _turn(_graph(parts, caller), "Write a palindrome checker")
    assert result["outcome"] == "tests_passed"
    assert result["triage"]["sentiment"] == "calm"
    assert store.list_tickets() == []


def test_ai_summary_absent_when_the_small_model_fails(parts):
    _, store = parts
    summary = FakeCaller({HandoffSummary: ModelUnavailableError("down")})
    _turn(_graph(parts, TurnCaller([tri("angry", "high", True)]), summary), STUDENT_C)
    (ticket,) = store.list_tickets()
    assert ticket.handoff_note.startswith("P1 (SLA 1 h)")
    assert "AI summary" not in ticket.handoff_note


def test_summary_caller_uses_the_small_model_and_chaos(parts):
    from codeforge.llm.chaos import ChaosCaller
    from codeforge.llm.factory import build_summary_caller
    settings, _ = parts
    inner = FakeCaller({})
    assert build_summary_caller(settings, inner) is inner
    chaotic = build_summary_caller(settings.model_copy(update={"chaos_rate": 0.6}), inner)
    assert isinstance(chaotic, ChaosCaller)
