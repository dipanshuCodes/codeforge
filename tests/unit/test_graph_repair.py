"""Repair loop through the real graph: scripted model, real sandbox (issue #7)."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import (
    TriageOutput,
    CodeOutput, Param, RepairOutput, Requirements, RouterOutput, TestsOutput,
)
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import ModelOutputError
from codeforge.runs.store import RunStore
from codeforge.sandbox.runner import ExecutionResult, run_pytest

REQUEST = "Write a Python function that checks if a string is a palindrome."
REQ = Requirements(function_name="is_palindrome", description="Palindrome check.",
                   params=[Param(name="s", type="str")], returns="bool", edge_cases=["empty"])
GOOD = "def is_palindrome(s):\n    return s == s[::-1]\n"
BAD_A = "def is_palindrome(s):\n    return False\n"
BAD_B = "def is_palindrome(s):\n    return False  # b\n"
BAD_C = "def is_palindrome(s):\n    return False  # c\n"
FILE_HELPER = "\n\ndef save(path, text):\n    with open(path, 'w') as f:\n        f.write(text)\n"
TESTS = (
    "from solution import is_palindrome\n\n"
    "def test_yes():\n    assert is_palindrome('aba')\n\n"
    "def test_no():\n    assert not is_palindrome('ab')\n"
)
FEWER_TESTS = "from solution import is_palindrome\n\ndef test_no():\n    assert not is_palindrome('ab')\n"
CFG = {"configurable": {"thread_id": "conv-1"}}


class ScriptedCaller:
    """Returns each schema's responses in order; the last one repeats."""

    def __init__(self, script):
        self._script = {k: list(v) for k, v in script.items()}
        self.calls = []

    def call(self, schema, system, user):
        self.calls.append((schema, system, user))
        queue = self._script[schema]
        value = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(value, Exception):
            raise value
        return value


class SpyRunner:
    def __init__(self, fake=None):
        self.calls = 0
        self.fake = fake

    def __call__(self, code, tests, **kw):
        self.calls += 1
        return self.fake if self.fake else run_pytest(code, tests, **kw)


def _script(codes, repairs=(), tests=TESTS):
    return {RouterOutput: [RouterOutput(kind="python_function")], Requirements: [REQ],
            CodeOutput: [c if isinstance(c, Exception) else CodeOutput(code=c) for c in codes],
            TestsOutput: [TestsOutput(tests=tests)], RepairOutput: list(repairs) or [None],
            TriageOutput: [TriageOutput(language="en", sentiment="calm", urgency="low",
                                        wants_human=False)]}


@pytest.fixture
def make(tmp_path):
    def _make(script, max_repairs=2, fake_result=None):
        settings = Settings(user_id="u-alice", role="student", db_path=str(tmp_path / "runs.db"),
                            sandbox_timeout_s=5, max_repair_attempts=max_repairs)
        store, spy = RunStore(settings), SpyRunner(fake_result)
        caller = ScriptedCaller(script)
        graph = build_graph(settings, caller, store, run_tests=spy, checkpointer=MemorySaver())
        return graph, store, spy, caller
    return _make


def _submit(graph, text=REQUEST):
    return graph.invoke({"raw_text": text}, CFG)


def test_default_budget_is_two_repairs():
    assert Settings(user_id="u", role="student").max_repair_attempts == 2


def test_repair_1_fixes_the_code_and_the_run_passes(make):
    graph, _, spy, _ = make(_script([BAD_A, GOOD]))
    final = _submit(graph)
    assert final["outcome"] == "tests_passed"
    assert spy.calls == 2
    assert final["repairs_tried"] == 1
    assert "Repairs:      1 of 2 tried" in final["report"]
    assert "TESTS PASSED" in final["report"]
    assert final["approved"] is None  # not left over from an earlier decision


def test_two_failed_repairs_report_the_real_failure_and_open_a_p3_ticket(make):
    graph, store, spy, _ = make(_script([BAD_A, BAD_B], repairs=[RepairOutput(code=BAD_C, tests=TESTS)]))
    final = _submit(graph)
    assert final["outcome"] == "tests_failed"
    assert spy.calls == 3
    assert "Repairs:      2 of 2 tried" in final["report"]
    assert "TESTS FAILED" in final["report"]
    assert final["ticket_id"]
    (ticket,) = store.list_tickets()  # R3 escalation rule: second failed Repair attempt
    assert (ticket.priority, ticket.sla_hours, ticket.reason) == ("P3", 24, "2 failed Repair attempts")
    assert ticket.ticket_id == final["ticket_id"]
    assert "last failing test: test_solution.py::" in ticket.handoff_note
    assert "P3, SLA 24 h" in final["report"]


def test_repair_that_deletes_a_failing_test_is_rejected_and_counted(make):
    graph, store, spy, _ = make(_script([BAD_A, BAD_B], repairs=[RepairOutput(code=GOOD, tests=FEWER_TESTS)]))
    final = _submit(graph)
    assert final["outcome"] == "tests_failed"
    assert spy.calls == 2  # the weakened repair never ran
    assert final["repairs_tried"] == 2
    assert "repair 2: rejected" in final["report"]
    assert final["tests"] == TESTS  # the original tests are kept
    assert final["ticket_id"]


def test_rejected_repair_1_does_not_stop_repair_2(make):
    graph, _, spy, _ = make(_script([BAD_A, BAD_A], repairs=[RepairOutput(code=GOOD, tests=TESTS)]))
    final = _submit(graph)  # repair 1 returns the same code: rejected before it can run
    assert final["outcome"] == "tests_passed"
    assert spy.calls == 2
    assert "repair 1: rejected" in final["report"]


def test_repair_missing_the_function_is_rejected(make):
    graph, _, spy, _ = make(_script([BAD_A, "def other(s):\n    return True\n"],
                                    repairs=[RepairOutput(code="x = 1\n", tests=TESTS)]))
    final = _submit(graph)
    assert final["outcome"] == "tests_failed"
    assert spy.calls == 1


def test_repaired_code_goes_through_the_policy_gate_again(make):
    bad_import = "import os\n" + GOOD
    graph, _, spy, _ = make(_script([BAD_A, bad_import]))
    final = _submit(graph)
    assert final["outcome"] == "denied"
    assert spy.calls == 1  # the denied repair never ran
    assert "DENIED" in final["report"]
    assert "repair 1: denied by the policy gate" in final["report"]


def test_repair_needing_approval_asks_again_and_reject_runs_nothing(make):
    graph, _, spy, _ = make(_script([BAD_A + FILE_HELPER, GOOD + FILE_HELPER]))
    first = _submit(graph)
    assert "__interrupt__" in first and spy.calls == 0
    second = graph.invoke(Command(resume="approve"), CFG)  # runs the original, fails, repairs
    assert "__interrupt__" in second  # the repaired code is untrusted too
    assert spy.calls == 1
    final = graph.invoke(Command(resume="reject"), CFG)
    assert final["outcome"] == "rejected"
    assert spy.calls == 1


def test_timeout_is_not_repaired(make):
    timeout = ExecutionResult(exit_code=None, timed_out=True, output="")
    graph, _, spy, caller = make(_script([GOOD, GOOD]), fake_result=timeout)
    final = _submit(graph)
    assert final["outcome"] == "timed_out"
    assert spy.calls == 1
    assert RepairOutput not in [c[0] for c in caller.calls]


def test_model_failure_during_repair_keeps_the_real_result(make):
    graph, _, spy, _ = make(_script([BAD_A, ModelOutputError("bad")]))
    final = _submit(graph)
    assert final["outcome"] == "tests_failed"
    assert spy.calls == 1
    assert "Repairs:      1 of 2 tried" in final["report"]
    assert "repair 1: the model gave no usable repair" in final["report"]


def test_no_repair_when_the_budget_is_zero(make):
    graph, _, spy, _ = make(_script([BAD_A]), max_repairs=0)
    final = _submit(graph)
    assert final["outcome"] == "tests_failed"
    assert spy.calls == 1
    assert "Repairs:" not in final["report"]
    assert not final["ticket_id"]


def test_passing_run_without_repair_shows_no_repair_line(make):
    graph, _, spy, _ = make(_script([GOOD]))
    final = _submit(graph)
    assert final["outcome"] == "tests_passed" and spy.calls == 1
    assert "Repairs:" not in final["report"]


def test_next_request_on_the_same_thread_starts_with_no_repairs(make):
    graph, _, _, _ = make(_script([BAD_A, GOOD, GOOD]))
    assert _submit(graph)["repairs_tried"] == 1
    second = _submit(graph, "Write a function that checks a palindrome, case-insensitively.")
    assert second["repairs_tried"] == 0
