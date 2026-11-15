"""Chaos run (R5): 20 Requests with 60% of model calls failing, fixed seed, offline.

Underneath the resilience layer sits a fake model, so the run is deterministic and needs no key.
The run's own approver answers "approve" so Executions happen; every Request must get an answer
that names its Serving tier. Writes the log to evals/chaos_run_log.txt.

    python scripts/chaos_run.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.agents.schemas import CodeOutput, Param, Requirements, RouterOutput, TestsOutput
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller
from codeforge.llm.factory import build_caller
from codeforge.runs.store import RunStore

REQUESTS = [
    "Write a function that checks if a string is a palindrome",
    "Write a function to reverse a string",
    "Write a function that returns the sum of a list of numbers",
    "Write a function that computes the factorial of n",
    "Is this word a palindrome? write a function",
    "reverse a string please",
    "sum a list of numbers",
    "factorial function",
    "Write a function that sorts words by length",       # unknown task: honest "cannot generate"
    "Write a function that finds the median of a list",  # unknown task
] * 2

_REQ = Requirements(function_name="is_palindrome", description="Palindrome check.",
                    params=[Param(name="s", type="str")], returns="bool", edge_cases=["empty"])
_CODE = "def is_palindrome(s):\n    return s == s[::-1]\n"
_TESTS = ("from solution import is_palindrome\n\n"
          "def test_yes():\n    assert is_palindrome('aba')\n\n"
          "def test_no():\n    assert not is_palindrome('ab')\n")


def _fake_model() -> FakeCaller:
    return FakeCaller({RouterOutput: RouterOutput(kind="python_function"), Requirements: _REQ,
                       CodeOutput: CodeOutput(code=_CODE), TestsOutput: TestsOutput(tests=_TESTS)})


def run_chaos(db_path: str, rate: float = 0.6, seed: int = 42) -> list[dict]:
    settings = Settings(user_id="u-chaos", role="student", db_path=db_path, run_quota=25,
                        chaos_rate=rate, chaos_seed=seed, sandbox_timeout_s=10)
    caller = build_caller(settings, _fake_model(), _fake_model())
    caller._sleep = lambda _s: None  # no real waiting in a demo run
    graph = build_graph(settings, caller, RunStore(settings), checkpointer=MemorySaver())
    rows = []
    for i, text in enumerate(REQUESTS):
        cfg = {"configurable": {"thread_id": f"chaos-{i}"}}
        result = graph.invoke({"raw_text": text}, cfg)
        if "__interrupt__" in result:
            result = graph.invoke(Command(resume="approve"), cfg)
        report = result.get("report") or ""
        tier = next((ln.split(":", 1)[1].strip() for ln in report.splitlines()
                     if ln.startswith("Serving tier:")), None)
        rows.append({"n": i + 1, "request": text, "outcome": result.get("outcome"), "tier": tier,
                     "answered": bool(report), "ticket": bool(result.get("ticket_id"))})
    return rows


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        rows = run_chaos(str(Path(tmp) / "chaos.db"))
    lines = ["Chaos run: rate=0.6 seed=42, fake model under the resilience layer", ""]
    for r in rows:
        lines.append(f"{r['n']:>2}. outcome={r['outcome']:<16} tier={str(r['tier']):<22} "
                     f"ticket={'yes' if r['ticket'] else 'no':<3} | {r['request']}")
    answered = sum(r["answered"] for r in rows)
    named = sum(1 for r in rows if r["tier"] or r["outcome"] == "cannot_generate")
    lines += ["", f"Answered: {answered}/{len(rows)}   Tier named or honest refusal: {named}/{len(rows)}"]
    out = Path(__file__).resolve().parent.parent / "evals" / "chaos_run_log.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if answered == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
