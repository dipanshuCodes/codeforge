"""Handoff note (R3): what the human picking up a Ticket needs. Built from masked fields only."""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from codeforge.privacy.masking import mask


def last_failing_test(output: str | None) -> str | None:
    """First `FAILED <node id>` line of pytest's short summary, without the message."""
    for line in (output or "").splitlines():
        if line.startswith("FAILED "):
            return line[len("FAILED "):].split(" - ", 1)[0].strip()
    return None


class HandoffNote(BaseModel):
    priority: str
    sla_hours: int
    reason: str
    request: str  # the masked Request
    attempts: int  # Executions in this Run
    last_failing_test: str | None = None
    ai_summary: str | None = None  # advisory, small model; absent on a model failure

    @field_validator("ai_summary")
    @classmethod
    def _mask_again(cls, v: str | None) -> str | None:
        # Model output is untrusted: masked again before it is shown or saved.
        return mask(v) if v else None

    def summary_line(self) -> str:
        failing = (f"last failing test: {self.last_failing_test}" if self.last_failing_test
                   else "no failing test")
        plural = "" if self.attempts == 1 else "s"
        return (f"{self.priority} (SLA {self.sla_hours} h): {self.reason}. "
                f"{self.attempts} Execution{plural}; {failing}.")

    def render(self) -> str:
        lines = [self.summary_line(), f"Request: {self.request}"]
        if self.ai_summary:
            lines.append(f"AI summary (advisory): {self.ai_summary}")
        return "\n".join(lines)
