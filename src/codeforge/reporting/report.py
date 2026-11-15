"""Template report. Filled only from recorded facts; the model writes none of it."""

from __future__ import annotations

from pydantic import BaseModel

from codeforge.reporting.outcome import Outcome, pytest_summary_line


class ReportInput(BaseModel):
    run_id: str
    request: str
    kind: str | None
    outcome: Outcome
    serving_tier: str | None
    model: str | None
    verdict: str | None
    reasons: list[str]
    approved: bool | None
    code: str | None
    tests: str | None
    exit_code: int | None
    timeout_s: float
    output: str | None
    ticket_id: str | None = None
    run_quota: int | None = None
    execution_reused: bool = False
    repairs_tried: int = 0
    max_repairs: int = 0
    repair_notes: list[str] = []


def _headline(r: ReportInput) -> str:
    if r.outcome == "tests_passed":
        return "TESTS PASSED"
    if r.outcome == "tests_failed":
        if r.exit_code == 0:
            return "NO TEST PASSED (pytest exit 0)"
        if r.exit_code is not None and r.exit_code != 1:
            return f"TESTS DID NOT RUN CLEANLY (pytest exit {r.exit_code})"
        return "TESTS FAILED"
    return {
        "timed_out": f"TIMED OUT after {r.timeout_s:g}s",
        "denied": "DENIED",
        "rejected": "REJECTED by the approver",
        "unsupported": "NOT SUPPORTED",
        "cannot_generate": "CANNOT GENERATE NOW",
        "quota_exceeded": f"QUOTA REACHED: {r.run_quota} Requests per day",
    }[r.outcome]


def _policy_line(r: ReportInput) -> str:
    if r.approved is True:
        decided = "approved at console"
    elif r.approved is False:
        decided = "rejected"
    else:
        decided = "—"
    return f"{r.verdict} → {decided}"


def render_report(r: ReportInput) -> str:
    """Render the console report for one Run."""
    lines = [f"Run {r.run_id[:6]} · {_headline(r)}", f"Request:      {r.request}"]
    if r.kind:
        lines.append(f"Kind:         {r.kind}")
    if r.serving_tier:
        model = f" ({r.model})" if r.model else ""
        lines.append(f"Serving tier: {r.serving_tier}{model}")
    if r.ticket_id:
        lines.append(f"Ticket:       {r.ticket_id[:8]} opened")
    if r.verdict:
        lines.append(f"Policy:       {_policy_line(r)}")
        lines.extend(f"              - {reason}" for reason in r.reasons)
    if r.exit_code is not None:
        summary = pytest_summary_line(r.output or "")
        result = f"pytest exit {r.exit_code}"
        lines.append(f'Result:       {result} · "{summary}"' if summary else f"Result:       {result}")
        if r.execution_reused:
            lines.append("              Execution reused: the same code and tests ran before")
    if r.repairs_tried:
        lines.append(f"Repairs:      {r.repairs_tried} of {r.max_repairs} tried")
        lines.extend(f"              - {note}" for note in r.repair_notes)
    if r.code:
        lines += ["── code ──", r.code.rstrip()]
    if r.tests:
        lines += ["── tests ──", r.tests.rstrip()]
    if r.outcome != "tests_passed" and r.output:
        lines += ["── output (first 10 KB) ──", r.output.rstrip()]
    return "\n".join(lines) + "\n"
