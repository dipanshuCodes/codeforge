"""Hidden Reference tests and the judge-like Request set (R6).

Correctness is judged by human-written Reference tests in evals/reference_tests/, never by the
model's own tests. Everything runs in the sandbox; generated code is never imported here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.policy.code_policy import evaluate_code_policy
from codeforge.reporting.outcome import outcome_from_execution
from codeforge.sandbox.runner import run_pytest

EVALS = Path(__file__).parents[1] / "evals"
JUDGE = json.loads((EVALS / "judge_requests.json").read_text(encoding="utf-8"))["requests"]
BAR = 0.90


def _reference(entry: dict) -> str:
    return (EVALS / "reference_tests" / entry["reference_test"]).read_text(encoding="utf-8")


def _passes(code: str, tests: str) -> bool:
    r = run_pytest(code, tests, timeout_s=10, max_output_bytes=10_240)
    return outcome_from_execution(r.exit_code, r.timed_out, r.output) == "tests_passed"


def test_judge_set_size_and_files():
    assert 10 <= len(JUDGE) <= 15
    assert len({e["id"] for e in JUDGE}) == len(JUDGE)
    on_disk = {p.name for p in (EVALS / "reference_tests").glob("test_*.py")}
    assert {e["reference_test"] for e in JUDGE} == on_disk


@pytest.mark.parametrize("entry", JUDGE, ids=[e["id"] for e in JUDGE])
def test_reference_test_accepts_the_human_solution(entry):
    # Proves each Reference test is right before it is used to judge generated code.
    assert _passes(entry["reference_solution"], _reference(entry))


@pytest.mark.llm
def test_judge_like_requests_pass_hidden_reference_tests(tmp_path):
    from codeforge.config import load_settings
    from codeforge.graph.build import build_graph
    from codeforge.llm.factory import build_caller
    from codeforge.runs.store import RunStore

    settings = load_settings({"CODEFORGE_USER_ID": "u-judge", "CODEFORGE_ROLE": "student",
                              "CODEFORGE_DB_PATH": str(tmp_path / "judge.db"),
                              "CODEFORGE_RUN_QUOTA": "100"})
    graph = build_graph(settings, build_caller(settings), RunStore(settings),
                        checkpointer=MemorySaver())
    failed = []
    for entry in JUDGE:
        cfg = {"configurable": {"thread_id": entry["id"]}}
        result = graph.invoke({"raw_text": entry["request"]}, cfg)
        while "__interrupt__" in result:  # risky code is not auto-approved by the eval
            result = graph.invoke(Command(resume="reject"), cfg)
        code = result.get("code")
        # Generated code goes through the policy gate before it runs, even in an eval.
        ok = (code is not None and evaluate_code_policy(code).verdict == "allow"
              and _passes(code, _reference(entry)))
        if not ok:
            failed.append(entry["id"])
    rate = 1 - len(failed) / len(JUDGE)
    assert rate >= BAR, f"judge-like pass rate {rate:.0%} < {BAR:.0%}; failed: {failed}"
