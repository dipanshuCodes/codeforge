"""Typed graph state. Routing reads only typed fields: kind, verdict, approved, outcome."""

from __future__ import annotations

from typing import Any, TypedDict

from codeforge.reporting.outcome import Outcome


class RunState(TypedDict, total=False):
    raw_text: str
    run_id: str
    conversation_id: str
    created_at: str
    request: str
    triage: dict[str, Any]
    escalation: str | None
    kind: str | None
    requirements: dict[str, Any] | None
    code: str | None
    tests: str | None
    verdict: str | None
    reasons: list[str]
    approved: bool | None
    execution: dict[str, Any] | None
    attempts: int
    serving_tier: str | None
    ticket_id: str | None
    outcome: Outcome | None
    report: str | None
    request_key: str
    duplicate_of: str | None


# Every per-Run field and its fresh value. Ingress returns these so a new Request on the same
# Conversation (thread_id) never inherits the previous Run's state.
RUN_DEFAULTS: dict[str, Any] = {
    "triage": {},
    "escalation": None,
    "kind": None,
    "requirements": None,
    "code": None,
    "tests": None,
    "verdict": None,
    "reasons": [],
    "approved": None,
    "execution": None,
    "attempts": 0,
    "serving_tier": None,
    "ticket_id": None,
    "outcome": None,
    "report": None,
    "duplicate_of": None,
}
