"""Feedback flywheel (R6): turn a thumbs-down into a draft Golden case.

The draft replays the Run offline (a `graph` case with the Run's code and tests canned) but its
expected outcome is left for a human: a model or a script never decides what "right" is.
"""

from __future__ import annotations

import ast
from typing import Any

from codeforge.runs.store import FeedbackRecord, RunRecord

TODO = "TODO: a human writes the expected outcome (and a Reference test if code is wrong)"


def _first_function(code: str) -> str:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return "TODO"
    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return names[0] if names else "TODO"


def draft_golden_case(feedback: FeedbackRecord, run: RunRecord) -> dict[str, Any]:
    code, tests = run.code or "", run.tests or ""
    return {
        "id": f"F-{feedback.feedback_id[:8]}",
        "tier": "hard",
        "area": "feedback",
        "check": "graph",
        "draft": True,
        "source": {"feedback_id": feedback.feedback_id, "run_id": run.run_id,
                   "reason": feedback.reason, "observed_outcome": run.outcome},
        "graph": {
            "requests": [run.request],  # already masked
            "real_sandbox": True,
            "model": {"kind": run.kind or "python_function",
                      "requirements": {"function_name": _first_function(code),
                                       "description": run.request, "params": [],
                                       "returns": "TODO", "edge_cases": []},
                      "code": code, "tests": tests},
        },
        "expect": {"outcomes": [TODO]},
    }
