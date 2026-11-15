"""R5 graph behaviour: tier named in the report, template tier in an outage, tickets, fail closed."""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import CodeOutput, Param, Requirements, RouterOutput, TestsOutput
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller, ModelUnavailableError
from codeforge.runs.store import RunStore
from codeforge.sandbox.runner import run_pytest

CODE = "def is_palindrome(s):\n    return s == s[::-1]\n"
TESTS = "from solution import is_palindrome\n\ndef test_a():\n    assert is_palindrome('aba')\n"
REQ = Requirements(function_name="is_palindrome", description="d", params=[Param(name="s", type="str")],
                   returns="bool", edge_cases=[])


def _responses():
    return {RouterOutput: RouterOutput(kind="python_function"), Requirements: REQ,
            CodeOutput: CodeOutput(code=CODE), TestsOutput: TestsOutput(tests=TESTS)}


OUTAGE = ModelUnavailableError("down", kind="server_unavailable")


class DownCaller:
    """Every call fails: a total outage."""

    last_tier = None

    def call(self, schema, system, user):
        raise OUTAGE


class FallbackCaller(FakeCaller):
    last_tier = "fallback"


@pytest.fixture
def parts(tmp_path):
    settings = Settings(user_id="u-alice", role="student", db_path=str(tmp_path / "r.db"),
                        sandbox_timeout_s=5)
    return settings, RunStore(settings)


def _run(parts, caller, text, answer="approve"):
    settings, store = parts
    graph = build_graph(settings, caller, store, run_tests=run_pytest, checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    result = graph.invoke({"raw_text": text}, cfg)
    if "__interrupt__" in result:
        result = graph.invoke(Command(resume=answer), cfg)
    return result


def test_outage_template_task_returns_code_tests_and_names_the_tier(parts):
    result = _run(parts, DownCaller(), "Write a function that checks if a string is a palindrome")
    assert result["outcome"] == "tests_passed"
    assert "Serving tier: template" in result["report"]
    assert "def is_palindrome" in result["report"]


def test_outage_unknown_task_is_honest_and_opens_a_ticket(parts):
    result = _run(parts, DownCaller(), "Write a function that sorts a list of strings by length")
    assert result["outcome"] == "cannot_generate"
    assert result["code"] is None
    assert "CANNOT GENERATE NOW" in result["report"]
    tickets = parts[1].list_tickets()
    assert len(tickets) == 1 and tickets[0].run_id == result["run_id"]


def test_outage_lookalike_task_is_not_given_a_template(parts):
    result = _run(parts, DownCaller(), "reverse a linked list")
    assert result["outcome"] == "cannot_generate" and result["code"] is None


def test_template_code_still_needs_the_approver(parts):
    result = _run(parts, DownCaller(), "reverse a string", answer="no")
    assert result["outcome"] == "rejected"  # degraded tier never runs without a human


def test_fallback_tier_is_named_in_the_report(parts):
    caller = FallbackCaller(_responses())
    result = _run(parts, caller, "Write a Python function that checks if a string is a palindrome.")
    assert "Serving tier: fallback" in result["report"]


def test_primary_tier_run_opens_no_ticket(parts):
    _run(parts, FakeCaller(_responses()), "Write a Python function that checks if a string is a palindrome.")
    assert parts[1].list_tickets() == []


def test_tickets_are_scoped_to_the_config_user(tmp_path):
    a = Settings(user_id="u-a", role="student", db_path=str(tmp_path / "r.db"))
    b = Settings(user_id="u-b", role="student", db_path=str(tmp_path / "r.db"))
    RunStore(a).add_ticket("run1", "outage", "template", "masked request")
    assert RunStore(b).list_tickets() == [] and len(RunStore(a).list_tickets()) == 1
