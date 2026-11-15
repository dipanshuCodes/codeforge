"""R6 gate: every Golden case in evals/golden_set.json.

Hard cases run offline with FakeCaller and must all pass; each is its own pytest item whose id
is the case id, so a red gate names the case. Soft cases call Groq and must pass at >= 85%.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import CodeOutput, Requirements, RouterOutput, TestsOutput
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller, ModelUnavailableError
from codeforge.llm.resilient import ResilientCaller
from codeforge.policy.code_policy import evaluate_code_policy
from codeforge.privacy.masking import mask
from codeforge.runs.store import RunStore
from codeforge.sandbox.runner import ExecutionResult, run_pytest

GOLDEN = Path(__file__).parents[1] / "evals" / "golden_set.json"
CASES: list[dict[str, Any]] = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
HARD = [c for c in CASES if c["tier"] == "hard"]
SOFT = [c for c in CASES if c["tier"] == "soft"]
OFFLINE_CHECKS = {"mask", "policy", "graph", "ownership"}
SOFT_CHECKS = {"route", "requirements", "escalation"}
SOFT_BAR = 0.85
# Built at runtime so no key-shaped literal sits in the repo; obviously fake.
FAKE_GROQ_KEY = "gsk_" + "FAKEfake0123456789abcdef"


def _fill(text: str) -> str:
    return text.replace("{FAKE_GROQ_KEY}", FAKE_GROQ_KEY)


# --- structure ---------------------------------------------------------------------------

def test_golden_set_shape():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    assert len(CASES) >= 20 and len(HARD) >= 10 and len(SOFT) >= 10
    for c in CASES:
        # A promoted Feedback draft joins the gate only after a human writes its expectation.
        assert not c.get("draft"), f"{c['id']}: still a draft; write its expected outcome"
    for c in HARD:
        assert c["check"] in OFFLINE_CHECKS, f"{c['id']}: hard cases must run offline"
    for c in SOFT:
        assert c["check"] in SOFT_CHECKS | OFFLINE_CHECKS, f"{c['id']}: unknown check"


# --- hard cases: offline, 100% -----------------------------------------------------------

class CountingRunner:
    """The sandbox, counted. With `real=False` nothing is ever executed, so a weakened policy
    can't run a destructive case."""

    def __init__(self, real: bool) -> None:
        self.real, self.calls = real, 0

    def __call__(self, code: str, tests: str, **kw: Any) -> ExecutionResult:
        self.calls += 1
        if self.real:
            return run_pytest(code, tests, **kw)
        return ExecutionResult(exit_code=1, timed_out=False, output="counting runner: not run")


def _canned(model: dict[str, Any]) -> dict[type, Any]:
    return {RouterOutput: RouterOutput(kind=model.get("kind", "python_function")),
            Requirements: Requirements.model_validate(model["requirements"]),
            CodeOutput: CodeOutput(code=model["code"]),
            TestsOutput: TestsOutput(tests=model["tests"])}


def _caller(spec: dict[str, Any]):
    model = spec["model"]
    schemas = (RouterOutput, Requirements, CodeOutput, TestsOutput)
    if model == "outage":
        return FakeCaller({s: ModelUnavailableError("503", kind="server_unavailable") for s in schemas})
    if spec.get("provider") == "429":
        # The real resilience layer: the primary always returns 429, the fallback answers.
        primary = FakeCaller({s: ModelUnavailableError("429", kind="rate_limit") for s in schemas})
        return ResilientCaller(primary, FakeCaller(_canned(model)), sleep=lambda _s: None)
    return FakeCaller(_canned(model))


def check_mask(case, tmp_path):
    assert mask(_fill(case["text"])) == case["expect"]["masked"]


def check_policy(case, tmp_path):
    decision = evaluate_code_policy(case["code"])
    assert decision.verdict == case["expect"]["verdict"], decision.reasons


def check_ownership(case, tmp_path):
    alice = Settings(user_id="u-alice", role="student", db_path=str(tmp_path / "runs.db"))
    canned = _canned(case["model"])
    graph = build_graph(alice, FakeCaller(canned), RunStore(alice),
                        run_tests=CountingRunner(real=False), checkpointer=MemorySaver())
    run_id = graph.invoke({"raw_text": case["request"]}, {"configurable": {"thread_id": "a"}})["run_id"]
    assert RunStore(alice).get(run_id) is not None
    bob = RunStore(alice.model_copy(update={"user_id": "u-bob"}))
    # "Not yours" and "missing" must be indistinguishable.
    assert bob.get(run_id) == bob.get("no-such-run") is None
    assert bob.list_mine() == []


def check_graph(case, tmp_path):
    spec, expect = case["graph"], case["expect"]
    settings = Settings(user_id="u-alice", role="student", db_path=str(tmp_path / "runs.db"),
                        sandbox_timeout_s=spec.get("timeout_s", 5),
                        run_quota=spec.get("run_quota", 5))
    caller = _caller(spec)
    runner = CountingRunner(real=spec.get("real_sandbox", False))
    store = RunStore(settings)
    graph = build_graph(settings, caller, store, run_tests=runner, checkpointer=MemorySaver())

    results = []
    for i, text in enumerate(spec["requests"]):
        cfg = {"configurable": {"thread_id": f"t{i}"}}
        result = graph.invoke({"raw_text": _fill(text)}, cfg)
        interrupted, runs_before_resume = "__interrupt__" in result, runner.calls
        while "__interrupt__" in result:
            result = graph.invoke(Command(resume=spec.get("approve", "")), cfg)
        results.append({**result, "interrupted": interrupted,
                        "runs_before_resume": runs_before_resume})
    last = results[-1]
    run = store.get(last["run_id"])

    assert [r["outcome"] for r in results] == expect["outcomes"]
    if "sandbox_runs" in expect:
        assert runner.calls == expect["sandbox_runs"], "sandbox ran a different number of times"
    if "interrupted" in expect:
        assert [r["interrupted"] for r in results] == expect["interrupted"]
    if "runs_before_resume" in expect:
        assert last["runs_before_resume"] == expect["runs_before_resume"]
    if "model_calls" in expect:
        calls = getattr(caller, "calls", None)
        assert calls is not None and len(calls) == expect["model_calls"]
    for word in expect.get("report_contains", []):
        assert word in last["report"], f"report lacks {word!r}"
    for word in expect.get("report_excludes", []):
        assert word not in last["report"], f"report must not contain {word!r}"
    if "serving_tier" in expect:
        assert run.serving_tier == expect["serving_tier"]
    if "tickets" in expect:
        assert len(store.list_tickets()) == expect["tickets"]
    if expect.get("no_code"):
        assert run.code is None and run.tests is None
    if expect.get("duplicate"):
        assert last.get("duplicate_of")
    for secret in expect.get("never_stored", []):
        raw = Path(settings.db_path).read_bytes()
        assert _fill(secret).encode() not in raw, "unmasked value reached the run store"
    if expect.get("owner_only"):
        # Identity comes from config: the Run belongs to the config User, not a claimed one.
        assert settings.role == "student"
        assert RunStore(settings.model_copy(update={"user_id": "u-bob"})).get(last["run_id"]) is None


OFFLINE = {"mask": check_mask, "policy": check_policy, "graph": check_graph,
           "ownership": check_ownership}


@pytest.mark.parametrize("case", HARD, ids=[c["id"] for c in HARD])
def test_hard_case(case, tmp_path):
    OFFLINE[case["check"]](case, tmp_path)


# --- soft cases: Groq, >= 85% ------------------------------------------------------------

def _soft_passes(case: dict[str, Any], tmp_path: Path) -> bool:
    from codeforge.agents.requirements import extract_requirements
    from codeforge.agents.router import classify
    from codeforge.config import load_settings
    from codeforge.llm.factory import build_caller

    if case["check"] in OFFLINE:
        try:
            OFFLINE[case["check"]](case, tmp_path)
            return True
        except AssertionError:
            return False
    settings = load_settings({"CODEFORGE_USER_ID": "u-eval", "CODEFORGE_ROLE": "student"})
    caller = build_caller(settings)
    request, expect = mask(case["request"]), case["expect"]
    try:
        if case["check"] == "route":
            return classify(caller, request).kind == expect["kind"]
        if case["check"] == "requirements":
            req = extract_requirements(caller, request)
            return (req.function_name == expect["function_name"]
                    and len(req.params) == expect["param_count"])
    except Exception:  # an unavailable model is a soft failure, not a crash
        return False
    raise AssertionError(f"{case['id']}: no soft runner for {case['check']}")


ACTIVE_SOFT = [c for c in SOFT if not c.get("pending")]
PENDING_SOFT = [c for c in SOFT if c.get("pending")]


@pytest.mark.llm
def test_soft_cases_pass_rate(tmp_path):
    failed = [c["id"] for c in ACTIVE_SOFT if not _soft_passes(c, tmp_path)]
    rate = 1 - len(failed) / len(ACTIVE_SOFT)
    assert rate >= SOFT_BAR, f"soft pass rate {rate:.0%} < {SOFT_BAR:.0%}; failed: {failed}"


@pytest.mark.parametrize("case", PENDING_SOFT, ids=[c["id"] for c in PENDING_SOFT])
def test_pending_soft_case(case):
    pytest.skip(f"pending {case['pending']}")
