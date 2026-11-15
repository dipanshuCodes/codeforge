import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import CodeOutput, Param, Requirements, RouterOutput, TestsOutput
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller, ModelOutputError, ModelUnavailableError
from codeforge.runs.store import RunStore
from codeforge.sandbox.runner import run_pytest

REQUEST = "Write a Python function that checks if a string is a palindrome."
REQ = Requirements(function_name="is_palindrome", description="Palindrome check.",
                   params=[Param(name="s", type="str")], returns="bool", edge_cases=["empty"])
CODE = "def is_palindrome(s):\n    return s == s[::-1]\n"
TESTS = (
    "from solution import is_palindrome\n\n"
    "def test_yes():\n    assert is_palindrome('aba')\n\n"
    "def test_no():\n    assert not is_palindrome('ab')\n"
)


class SpyRunner:
    def __init__(self):
        self.calls = 0

    def __call__(self, code, tests, **kw):
        self.calls += 1
        return run_pytest(code, tests, **kw)


def _responses(overrides=None):
    r = {RouterOutput: RouterOutput(kind="python_function"), Requirements: REQ,
         CodeOutput: CodeOutput(code=CODE), TestsOutput: TestsOutput(tests=TESTS)}
    r.update(overrides or {})
    return r


@pytest.fixture
def env(tmp_path):
    settings = Settings(user_id="u-alice", role="student", db_path=str(tmp_path / "runs.db"),
                        sandbox_timeout_s=5)
    return settings, RunStore(settings), MemorySaver(), SpyRunner()


def _graph(env, overrides=None):
    settings, store, saver, spy = env
    return build_graph(settings, FakeCaller(_responses(overrides)), store,
                       run_tests=spy, checkpointer=saver)


CFG = {"configurable": {"thread_id": "conv-1"}}


def _submit(graph, text=REQUEST, cfg=CFG):
    return graph.invoke({"raw_text": text}, cfg)


def test_palindrome_happy_path(env):
    _, store, _, spy = env
    g = _graph(env)
    first = _submit(g)
    payload = first["__interrupt__"][0].value
    assert payload["verdict"] == "needs_approval"
    assert payload["code"] == CODE and payload["tests"] == TESTS
    assert spy.calls == 0
    final = g.invoke(Command(resume="approve"), CFG)
    assert final["outcome"] == "tests_passed"
    assert "TESTS PASSED" in final["report"]
    assert store.get(final["run_id"]).outcome == "tests_passed"
    assert spy.calls == 1


def test_reject_runs_nothing(env):
    g = _graph(env)
    _submit(g)
    final = g.invoke(Command(resume="reject"), CFG)
    assert final["outcome"] == "rejected"
    assert "REJECTED by the approver" in final["report"]
    assert env[3].calls == 0


@pytest.mark.parametrize("answer", ["", "y", "yes", "approve it", True, {"approve": True}])
def test_non_exact_approval_rejects(env, answer):
    g = _graph(env)
    _submit(g)
    assert g.invoke(Command(resume=answer), CFG)["outcome"] == "rejected"
    assert env[3].calls == 0


def test_approval_ignores_case_and_spaces(env):
    g = _graph(env)
    _submit(g)
    assert g.invoke(Command(resume="  Approve "), CFG)["outcome"] == "tests_passed"


def test_unparsable_tests_denied_without_interrupt(env):
    g = _graph(env, {TestsOutput: TestsOutput(tests="def test_x(:")})
    final = _submit(g)
    assert "__interrupt__" not in final
    assert final["outcome"] == "denied"
    assert "DENIED" in final["report"]
    assert env[3].calls == 0


def test_bad_router_output_is_unsupported(env):
    final = _submit(_graph(env, {RouterOutput: ModelOutputError("bad")}))
    assert final["outcome"] == "unsupported"


def test_router_outage_is_cannot_generate(env):
    final = _submit(_graph(env, {RouterOutput: ModelUnavailableError("429")}))
    assert final["outcome"] == "cannot_generate"


def test_sql_kind_is_unsupported(env):
    final = _submit(_graph(env, {RouterOutput: RouterOutput(kind="sql_query")}))
    assert final["outcome"] == "unsupported"
    assert "NOT SUPPORTED" in final["report"]


def test_codegen_error_cannot_generate(env):
    final = _submit(_graph(env, {CodeOutput: ModelOutputError("bad")}))
    assert final["outcome"] == "cannot_generate"
    assert "CANNOT GENERATE NOW" in final["report"]
    assert env[3].calls == 0


def test_missing_function_name_cannot_generate(env):
    final = _submit(_graph(env, {CodeOutput: CodeOutput(code="def other(s):\n    return 1\n")}))
    assert final["outcome"] == "cannot_generate"


def test_failing_tests_no_repair_in_l1(env):
    g = _graph(env, {CodeOutput: CodeOutput(code="def is_palindrome(s):\n    return False\n")})
    _submit(g)
    final = g.invoke(Command(resume="approve"), CFG)
    assert final["outcome"] == "tests_failed"
    assert env[3].calls == 1


def test_zero_tests_never_passes(env):
    g = _graph(env, {TestsOutput: TestsOutput(tests="x = 1\n")})
    _submit(g)
    final = g.invoke(Command(resume="approve"), CFG)
    assert final["outcome"] == "tests_failed"
    assert "TESTS PASSED" not in final["report"]


def test_second_request_same_thread_starts_clean(env):
    settings, store, saver, spy = env
    g1 = _graph(env)
    _submit(g1)
    first = g1.invoke(Command(resume="reject"), CFG)

    code2 = "def is_palindrome(s):\n    return s.lower() == s.lower()[::-1]\n"
    g2 = _graph(env, {CodeOutput: CodeOutput(code=code2)})
    second = _submit(g2, "Make it case-insensitive.")
    payload = second["__interrupt__"][0].value
    assert payload["run_id"] != first["run_id"]
    assert payload["code"] == code2
    assert second["outcome"] is None
    assert second["approved"] is None
    assert store.get(first["run_id"]).outcome == "rejected"


def test_run_saved_at_ingress_before_approval(env):
    _, store, _, _ = env
    first = _submit(_graph(env))
    run_id = first["__interrupt__"][0].value["run_id"]
    rec = store.get(run_id)
    assert rec is not None and rec.request == REQUEST and rec.conversation_id == "conv-1"


def test_all_skipped_tests_never_pass(env):
    skipped = "import pytest\n\n@pytest.mark.skip\ndef test_x():\n    pass\n"
    g = _graph(env, {TestsOutput: TestsOutput(tests=skipped)})
    _submit(g)
    final = g.invoke(Command(resume="approve"), CFG)
    assert final["outcome"] == "tests_failed"
    assert "TESTS PASSED" not in final["report"]
