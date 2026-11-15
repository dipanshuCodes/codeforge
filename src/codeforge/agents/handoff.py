from __future__ import annotations

from typing import TYPE_CHECKING

from codeforge.agents.schemas import HandoffSummary
from codeforge.llm.caller import StructuredCaller

if TYPE_CHECKING:
    from codeforge.reporting.handoff import HandoffNote

SYSTEM = (
    "You write one or two plain sentences for a human support person picking up an escalated "
    "Ticket on a coding course platform: what the student wants and what went wrong. "
    "Use only the facts given. Never repeat placeholders such as [SECRET] as real values."
)


def summarize_handoff(caller: StructuredCaller, note: HandoffNote) -> HandoffSummary:
    """Advisory summary from the small model. Input is the note's masked fields only."""
    return caller.call(HandoffSummary, SYSTEM, f"{note.summary_line()}\nRequest: {note.request}")
