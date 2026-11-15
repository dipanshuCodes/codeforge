"""R1 at the graph level: masking reaches everything, quota refuses before any model call,
and identity claims in the message change nothing. Fake model, fake values only."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import CodeOutput, Param, Requirements, RouterOutput, TestsOutput
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller, ModelUnavailableError
from codeforge.runs.store import RunStore
from codeforge.sandbox.runner import run_pytest

FAKE_KEY = "gsk_" + "FAKEfake0123456789abcdef"
FAKE_AADHAAR = "2345 6789 0123"
REQ = Requirements(function_name="add", description="Add two ints.",
                   params=[Param(name="a", type="int"), Param(name="b", type="int")],
                   returns="int", edge_cases=[])
CODE = "def add(a, b):\n    return a + b\n"
TESTS = "from solution import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def _responses():
    return {RouterOutput: RouterOutput(kind="python_function"), Requirements: REQ,
            CodeOutput: CodeOutput(code=CODE), TestsOutput: TestsOutput(tests=TESTS)}


def _setup(tmp_path, user="u-alice", quota=5, responses=None):
    settings = Settings(user_id=user, role="student", db_path=str(tmp_path / "runs.db"),
                        sandbox_timeout_s=5, run_quota=quota)
    caller = FakeCaller(responses or _responses())
    store = RunStore(settings)
    graph = build_graph(settings, caller, store, run_tests=run_pytest, checkpointer=MemorySaver())
    return graph, caller, store, settings


def _run(graph, text, thread="t1", answer="approve"):
    cfg = {"configurable": {"thread_id": thread}}
    result = graph.invoke({"raw_text": text}, cfg)
    while "__interrupt__" in result:
        result = graph.invoke(Command(resume=answer), cfg)
    return result


def test_quota_refuses_before_any_model_call(tmp_path):
    graph, caller, store, _ = _setup(tmp_path, quota=2)
    _run(graph, "add two numbers", thread="a")
    _run(graph, "add two numbers", thread="b")  # a Duplicate Request still counts
    calls_before = len(caller.calls)
    refused = _run(graph, "add two numbers", thread="c")
    assert refused["outcome"] == "quota_exceeded"
    assert "QUOTA REACHED" in refused["report"]
    assert len(caller.calls) == calls_before
    # The refusal itself does not use up quota for later days; it is stored but not counted.
    assert store.get(refused["run_id"]).outcome == "quota_exceeded"


def test_transient_failure_does_not_use_quota(tmp_path):
    down = {RouterOutput: ModelUnavailableError("503")}
    graph, _, _, _ = _setup(tmp_path, quota=1, responses=down)
    first = _run(graph, "add two numbers", thread="a")
    assert first["outcome"] == "cannot_generate"
    second = _run(graph, "add two numbers", thread="b")
    assert second["outcome"] == "cannot_generate"  # not quota_exceeded
