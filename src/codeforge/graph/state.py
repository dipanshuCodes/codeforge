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
    repairs_tried: int
    repair_status: str | None  # proposed | rejected | failed
    repair_notes: list[str]
    ticket_priority: str | None
    ticket_sla_hours: int | None
    # Conversation-level (R3): not in RUN_DEFAULTS, so they survive between turns of a thread_id.
    unhappy_turns: int
    denials: int
    failed_repairs: int
    conversation_ticket_id: str | None
    conversation_ticket_priority: str | None


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
    "repairs_tried": 0,
    "repair_status": None,
    "repair_notes": [],
    "ticket_priority": None,
    "ticket_sla_hours": None,
}
