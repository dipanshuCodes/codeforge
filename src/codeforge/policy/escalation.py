"""Escalation rules (R3). Pure: the Triage agent supplies signals, this code decides.

First match wins. Only P1 skips generation; P2/P3 open a Ticket and the Run continues.
Counters accumulate across one Conversation (LangGraph thread_id).
"""

from __future__ import annotations

from dataclasses import dataclass

_RANK = {"P1": 1, "P2": 2, "P3": 3}


@dataclass(frozen=True)
class Signals:
    wants_human: bool
    sentiment: str  # calm / mildly_unhappy / angry
    urgency: str  # low / high
    unhappy_turns: int  # mildly unhappy turns so far in the Conversation, this one included
    denials: int  # policy denials so far in the Conversation
    failed_repairs: int  # failed Repair attempts so far in the Conversation


@dataclass(frozen=True)
class Escalation:
    priority: str
    sla_hours: int
    reason: str


def decide_escalation(s: Signals) -> Escalation | None:
    """The Ticket a Conversation needs now, or None."""
    angry = s.sentiment == "angry"
    if s.wants_human and (angry or s.urgency == "high"):
        return Escalation("P1", 1, "asked for a human; angry or urgent")
    if angry:
        return Escalation("P2", 4, "angry")
    if s.wants_human:
        return Escalation("P2", 4, "asked for a human")
    if s.unhappy_turns >= 2:
        return Escalation("P3", 24, f"{s.unhappy_turns} mildly unhappy turns")
    if s.denials >= 2:
        return Escalation("P3", 24, f"{s.denials} policy denials")
    if s.failed_repairs >= 2:
        return Escalation("P3", 24, f"{s.failed_repairs} failed Repair attempts")
    return None


def skips_generation(priority: str | None) -> bool:
    return priority == "P1"


def opens_ticket(priority: str, already_opened: str | None) -> bool:
    """One Ticket per Conversation, unless the new priority is stricter than the open one."""
    return already_opened is None or _RANK[priority] < _RANK[already_opened]


def failed_repairs_in_run(repairs_tried: int, passed: bool) -> int:
    """Failed Repair attempts in one Run. A rejected repair counts as tried; if the Run passed,
    the last repair is the one that worked."""
    return max(0, repairs_tried - 1) if passed else repairs_tried
