"""R2 run-once behaviour through the graph: Request key and Execution key. Fake model."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import CodeOutput, Param, Requirements, RouterOutput, TestsOutput
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller, ModelUnavailableError
from codeforge.runs.store import RunStore
from codeforge.sandbox.runner import run_pytest

REQ = Requirements(function_name="add", description="Add two ints.",
                   params=[Param(name="a", type="int"), Param(name="b", type="int")],
                   returns="int", edge_cases=[])
CODE = "def add(a, b):\n    return a + b\n"
TESTS = "from solution import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"


class Spy:
    def __init__(self):
        self.calls = 0

    def __call__(self, code, tests, **kw):
        self.calls += 1
        return run_pytest(code, tests, **kw)


def _responses(over=None):
    r = {RouterOutput: RouterOutput(kind="python_function"), Requirements: REQ,
         CodeOutput: CodeOutput(code=CODE), TestsOutput: TestsOutput(tests=TESTS)}
    r.update(over or {})
    return r


@pytest.fixture
def make(tmp_path):
    spy = Spy()

    def _make(user="u-alice", responses=None):
        settings = Settings(user_id=user, role="student", db_path=str(tmp_path / "runs.db"),
                            sandbox_timeout_s=5, run_quota=50)
        caller = FakeCaller(responses or _responses())
        store = RunStore(settings)
        graph = build_graph(settings, caller, store, run_tests=spy, checkpointer=MemorySaver())
        return graph, caller, store
    return _make, spy


def _run(graph, text, thread, answer="approve"):
    cfg = {"configurable": {"thread_id": thread}}
    result = graph.invoke({"raw_text": text}, cfg)
    while "__interrupt__" in result:
        result = graph.invoke(Command(resume=answer), cfg)
    return result


def test_same_request_twice_runs_once(make):
    _make, spy = make
    graph, caller, store = _make()
    first = _run(graph, "add two numbers", "a")
    calls = len(caller.calls)
    second = _run(graph, "add two numbers", "b")
    assert first["outcome"] == second["outcome"] == "tests_passed"
    assert spy.calls == 1 and len(caller.calls) == calls  # no model call, no Execution
    assert second["duplicate_of"] == first["run_id"] and second["run_id"] != first["run_id"]
    assert f"Duplicate Request: same as Run {first['run_id'][:6]}" in second["report"]
    assert store.get(second["run_id"]).duplicate_of == first["run_id"]


def test_duplicate_is_matched_on_masked_text(make):
    _make, spy = make
    graph, _, _ = _make()
    _run(graph, "add two numbers, mail a@b.io", "a")
    second = _run(graph, "add two numbers, mail c@d.io", "b")  # both mask to [EMAIL]
    assert second.get("duplicate_of") and spy.calls == 1


def test_transient_failure_is_processed_again(make):
    _make, spy = make
    graph, _, _ = _make(responses=_responses({RouterOutput: ModelUnavailableError("503")}))
    assert _run(graph, "add two numbers", "a")["outcome"] == "cannot_generate"
    graph, _, _ = _make()
    second = _run(graph, "add two numbers", "b")
    assert second.get("duplicate_of") is None and second["outcome"] == "tests_passed"
    assert spy.calls == 1


def test_another_users_identical_request_is_not_a_duplicate(make):
    _make, spy = make
    _run(_make("u-alice")[0], "add two numbers", "a")
    other = _run(_make("u-bob")[0], "add two numbers", "b")
    assert other.get("duplicate_of") is None and spy.calls == 2


def test_same_code_and_tests_execute_once(make):
    _make, spy = make
    graph, _, _ = _make()
    first = _run(graph, "add two numbers", "a")
    second = _run(graph, "please add two integers", "b")  # different Request, same code+tests
    assert second.get("duplicate_of") is None
    assert first["outcome"] == second["outcome"] == "tests_passed"
    assert spy.calls == 1
    assert "Execution reused" in second["report"]
