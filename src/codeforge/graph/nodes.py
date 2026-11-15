"""Graph nodes. Agents propose; the deterministic code here decides and records."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from codeforge.agents.codegen import generate_code
from codeforge.agents.repair import repair_code, repair_code_and_tests
from codeforge.agents.handoff import summarize_handoff
from codeforge.agents.requirements import extract_requirements
from codeforge.agents.router import classify
from codeforge.agents.schemas import Requirements, TriageOutput
from codeforge.agents.testgen import generate_tests
from codeforge.agents.triage import triage as triage_request
from codeforge.config import Settings
from codeforge.graph.state import RUN_DEFAULTS, RunState
from codeforge.llm.caller import ModelCallError, ModelOutputError, ModelUnavailableError, StructuredCaller
from codeforge.policy.escalation import (
    Signals, decide_escalation, failed_repairs_in_run, opens_ticket, skips_generation,
)
from codeforge.policy.code_policy import defines_function, evaluate_code_policy, strictest
from codeforge.policy.repair import evaluate_repair
from codeforge.policy.quota import NOT_COUNTED, quota_allows, quota_window_start
from codeforge.policy.resilience import degrade_verdict, worst_tier
from codeforge.policy.templates import pick_template
from codeforge.privacy.masking import mask
from codeforge.reporting.handoff import HandoffNote, last_failing_test
from codeforge.reporting.outcome import outcome_from_execution
from codeforge.reporting.report import ReportInput, render_report
from codeforge.runs.keys import execution_key, request_key
from codeforge.runs.store import RunRecord, RunStore
from codeforge.sandbox.runner import ExecutionResult

APPROVE_WORD = "approve"
# Triage unavailable: assume calm so the Run is not blocked (R5 still tickets an outage).
CALM = TriageOutput(language="en", sentiment="calm", urgency="low", wants_human=False)


class Nodes:
    def __init__(
        self,
        settings: Settings,
        caller: StructuredCaller,
        store: RunStore,
        run_tests: Callable[..., ExecutionResult],
        summary_caller: StructuredCaller | None = None,
    ) -> None:
        self.settings = settings
        self.caller = caller
        self.store = store
        self.run_tests = run_tests
        self.summary_caller = summary_caller  # small model for the Handoff note; None = absent

    # --- ingress / triage / escalation -------------------------------------------------

    def ingress(self, state: RunState, config: RunnableConfig) -> dict[str, Any]:
        request = mask(state["raw_text"])  # first, before anything is stored or sent
        run_id = uuid.uuid4().hex
        conversation_id = str(config["configurable"]["thread_id"])
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        # Counted before this Run is saved, so `used` is the Requests already submitted today.
        used = self.store.count_since(quota_window_start(now).isoformat(), NOT_COUNTED)
        allowed = quota_allows(used, self.settings.run_quota)
        key = request_key(self.settings.user_id, request)
        # raw_text is overwritten with the masked text so the unmasked form isn't checkpointed.
        update = {**RUN_DEFAULTS, "raw_text": request, "request": request, "run_id": run_id,
                  "conversation_id": conversation_id, "created_at": created_at,
                  "request_key": key}
        if not allowed:
            update["outcome"] = "quota_exceeded"
        elif (earlier := self.store.find_final_run(key)) is not None:
            # Duplicate Request: answer with the stored Run; nothing is generated or run.
            report = (f"Duplicate Request: same as Run {earlier.run_id[:6]}; not run again.\n"
                      + (earlier.report or ""))
            self.store.save(earlier.model_copy(update={
                "run_id": run_id, "conversation_id": conversation_id, "created_at": created_at,
                "duplicate_of": earlier.run_id, "report": report}))
            return {**update, "outcome": earlier.outcome, "report": report,
                    "duplicate_of": earlier.run_id}
        self.store.save(RunRecord(run_id=run_id, conversation_id=conversation_id,
                                  created_at=created_at, request=request, request_key=key,
                                  outcome=update.get("outcome")))
        return update

    def triage(self, state: RunState) -> dict[str, Any]:
        try:
            out = triage_request(self.caller, state["request"])  # already masked at ingress
        except ModelCallError:
            out = CALM
        unhappy = state.get("unhappy_turns", 0) + (out.sentiment == "mildly_unhappy")
        return {"triage": out.model_dump(), "unhappy_turns": unhappy}

    def escalation(self, state: RunState) -> dict[str, Any]:
        update = self._escalate(state)
        if skips_generation(update.get("escalation")):
            update["outcome"] = "escalated"  # P1: a human takes over, nothing is generated
        return update

    def _escalate(self, state: RunState, **counts: int) -> dict[str, Any]:
        """Decide from triage + Conversation counters; open a Ticket if the rules say so."""
        t = state.get("triage") or {}
        signals = Signals(
            wants_human=bool(t.get("wants_human")), sentiment=t.get("sentiment", "calm"),
            urgency=t.get("urgency", "low"),
            unhappy_turns=counts.get("unhappy_turns", state.get("unhappy_turns", 0)),
            denials=counts.get("denials", state.get("denials", 0)),
            failed_repairs=counts.get("failed_repairs", state.get("failed_repairs", 0)),
        )
        esc = decide_escalation(signals)
        if esc is None:
            return {}
        if not opens_ticket(esc.priority, state.get("conversation_ticket_priority")):
            if not skips_generation(esc.priority):
                return {}
            # A repeated P1: point at the Ticket already open for this Conversation.
            return {"escalation": esc.priority, "ticket_id": state.get("conversation_ticket_id"),
                    "ticket_priority": state.get("conversation_ticket_priority"),
                    "ticket_sla_hours": esc.sla_hours}
        execution = state.get("execution") or {}
        note = HandoffNote(priority=esc.priority, sla_hours=esc.sla_hours, reason=esc.reason,
                           request=state["request"], attempts=state.get("attempts", 0),
                           last_failing_test=last_failing_test(execution.get("output")))
        if self.summary_caller is not None:
            try:
                summary = summarize_handoff(self.summary_caller, note).summary
                # Re-validated (not model_copy) so the AI summary is masked again.
                note = HandoffNote(**{**note.model_dump(), "ai_summary": summary})
            except ModelCallError:
                pass  # advisory only: absent during an outage
        ticket_id = self.store.add_ticket(state["run_id"], esc.reason, None, state["request"],
                                          priority=esc.priority, sla_hours=esc.sla_hours,
                                          handoff_note=note.render())
        return {"escalation": esc.priority, "ticket_id": ticket_id,
                "ticket_priority": esc.priority, "ticket_sla_hours": esc.sla_hours,
                "conversation_ticket_id": ticket_id,
                "conversation_ticket_priority": esc.priority}

    # --- model nodes ---------------------------------------------------------------------

    def _tier(self, state: RunState) -> str | None:
        """Most degraded tier used so far in this Run. A caller without tiers is `primary`."""
        used = getattr(self.caller, "last_tier", None) or "primary"
        return worst_tier(state.get("serving_tier"), used)

    def _outage(self, state: RunState) -> dict[str, Any]:
        """Both model tiers failed: serve a strict Template match, else say so and open a Ticket.

        Never invents code for an unknown task.
        """
        template = pick_template(state["request"])
        if template is not None:
            return {"kind": "python_function", "serving_tier": "template",
                    "requirements": template.requirements.model_dump(),
                    "code": template.code, "tests": template.tests}
        ticket_id = self.store.add_ticket(state["run_id"], "model outage, no template match",
                                          "template", state["request"])
        return {"outcome": "cannot_generate", "serving_tier": "template", "ticket_id": ticket_id,
                "ticket_priority": None, "ticket_sla_hours": None}

    def router(self, state: RunState) -> dict[str, Any]:
        try:
            kind = classify(self.caller, state["request"]).kind
        except ModelOutputError:
            kind = "other"  # fail closed: unreadable classification is not served
        except ModelUnavailableError:
            return self._outage(state)
        except ModelCallError:
            return {"outcome": "cannot_generate"}
        if kind != "python_function":
            return {"kind": kind, "outcome": "unsupported", "serving_tier": self._tier(state)}
        return {"kind": kind, "serving_tier": self._tier(state)}

    def requirements(self, state: RunState) -> dict[str, Any]:
        if state.get("serving_tier") == "template":
            return {}  # the Template tier already filled requirements, code and tests
        try:
            req = extract_requirements(self.caller, state["request"])
        except ModelUnavailableError:
            return self._outage(state)
        except ModelCallError:
            return {"outcome": "cannot_generate"}
        return {"requirements": req.model_dump(), "serving_tier": self._tier(state)}

    def codegen(self, state: RunState) -> dict[str, Any]:
        if state.get("serving_tier") == "template":
            return {}
        req = Requirements.model_validate(state["requirements"])
        try:
            code = generate_code(self.caller, req).code
        except ModelUnavailableError:
            return self._outage(state)
        except ModelCallError:
            return {"outcome": "cannot_generate"}
        tier = self._tier(state)
        if not defines_function(code, req.function_name):
            return {"code": code, "outcome": "cannot_generate", "serving_tier": tier}
        return {"code": code, "serving_tier": tier}

    def testgen(self, state: RunState) -> dict[str, Any]:
        if state.get("serving_tier") == "template":
            return {}
        req = Requirements.model_validate(state["requirements"])
        try:
            tests = generate_tests(self.caller, req, state["code"]).tests
        except ModelUnavailableError:
            return self._outage(state)
        except ModelCallError:
            return {"outcome": "cannot_generate"}
        return {"tests": tests, "serving_tier": self._tier(state)}

    # --- policy / approval / execute ----------------------------------------------------

    def policy(self, state: RunState) -> dict[str, Any]:
        decision = strictest(evaluate_code_policy(state["code"]), evaluate_code_policy(state["tests"]))
        # A degraded tier never auto-approves (fail closed).
        verdict = degrade_verdict(decision.verdict, state.get("serving_tier"))
        update: dict[str, Any] = {"verdict": verdict, "reasons": decision.reasons}
        if decision.verdict == "deny":
            update["outcome"] = "denied"
            self._note_after_repair(state, update, "denied by the policy gate")
        return update

    @staticmethod
    def _note_after_repair(state: RunState, update: dict[str, Any], what: str) -> None:
        """A repair that never ran must not look like a fresh result: say where the shown
        pytest result came from."""
        n = state.get("repairs_tried", 0)
        if n:
            update["repair_notes"] = [*state.get("repair_notes", []),
                                      f"repair {n}: {what}; the pytest result is from the previous Execution"]

    def approval(self, state: RunState) -> dict[str, Any]:
        answer = interrupt({
            "run_id": state["run_id"],
            "verdict": state["verdict"],
            "reasons": state["reasons"],
            "code": state["code"],
            "tests": state["tests"],
        })
        # Approval is an explicit act: only the exact word counts; anything else rejects.
        approved = isinstance(answer, str) and answer.strip().lower() == APPROVE_WORD
        if not approved:
            update = {"approved": False, "outcome": "rejected"}
            self._note_after_repair(state, update, "rejected by the approver")
            return update
        return {"approved": True}

    def execute(self, state: RunState) -> dict[str, Any]:
        key = execution_key(self.settings.user_id, state["code"], state["tests"])
        execution = self.store.get_execution(key)
        if execution is not None:
            execution["reused"] = True  # same code + tests ran before: not run again
        else:
            execution = self.run_tests(
                state["code"], state["tests"],
                timeout_s=self.settings.sandbox_timeout_s,
                max_output_bytes=self.settings.max_output_bytes,
                memory_limit_bytes=self.settings.sandbox_memory_bytes,
            ).model_dump()
            self.store.save_execution(key, execution)
        return {"execution": execution, "attempts": state.get("attempts", 0) + 1}

    def repair(self, state: RunState) -> dict[str, Any]:
        """One Repair attempt: the agent proposes, `evaluate_repair` decides. A proposal that
        passes goes back through the policy gate; a rejected one still counts as an attempt."""
        attempt = state.get("repairs_tried", 0) + 1
        notes = list(state.get("repair_notes", []))
        req = Requirements.model_validate(state["requirements"])
        code, tests = state["code"], state["tests"]
        output = (state.get("execution") or {}).get("output") or ""
        try:
            if attempt == 1:
                new_code, new_tests = repair_code(self.caller, req, code, tests, output).code, tests
            else:
                out = repair_code_and_tests(self.caller, req, code, tests, output)
                new_code, new_tests = out.code, out.tests
        except ModelCallError:
            notes.append(f"repair {attempt}: the model gave no usable repair")
            return {"repairs_tried": attempt, "repair_status": "failed", "repair_notes": notes}
        decision = evaluate_repair(attempt, code, tests, new_code, new_tests)
        reasons = list(decision.reasons)
        if decision.accepted and not defines_function(new_code, req.function_name):
            reasons.append(f"repair does not define `{req.function_name}`")
        if reasons:
            notes.append(f"repair {attempt}: rejected: {'; '.join(reasons)}")
            return {"repairs_tried": attempt, "repair_status": "rejected", "repair_notes": notes,
                    "serving_tier": self._tier(state)}
        # Fresh gate decision for the repaired files; nothing carries over from the last one.
        return {"code": new_code, "tests": new_tests, "repairs_tried": attempt,
                "repair_status": "proposed", "repair_notes": notes,
                "verdict": None, "reasons": [], "approved": None,
                "serving_tier": self._tier(state)}

    # --- report --------------------------------------------------------------------------

    def report(self, state: RunState) -> dict[str, Any]:
        execution = state.get("execution") or {}
        outcome = state.get("outcome") or outcome_from_execution(
            execution.get("exit_code"), bool(execution.get("timed_out")), execution.get("output") or ""
        )
        tried, budget = state.get("repairs_tried", 0), self.settings.max_repair_attempts
        # This Run's denial / failed Repair attempts count now, so the second one escalates here.
        counts = {"denials": state.get("denials", 0) + (outcome == "denied"),
                  "failed_repairs": state.get("failed_repairs", 0)
                  + failed_repairs_in_run(tried, outcome == "tests_passed")}
        escalated: dict[str, Any] = {}
        if outcome != "escalated" and (counts["denials"] != state.get("denials", 0)
                                       or counts["failed_repairs"] != state.get("failed_repairs", 0)):
            escalated = self._escalate(state, **counts)
            state = {**state, **escalated}
        ticket_id = state.get("ticket_id")
        tier = state.get("serving_tier") if state.get("code") is not None else None
        if ticket_id:
            tier = state.get("serving_tier")  # name the tier even when nothing was generated
        model = {"primary": self.settings.primary_model,
                 "secondary": self.settings.secondary_model,
                 "fallback": self.settings.fallback_model}.get(tier or "")
        report = render_report(ReportInput(
            run_id=state["run_id"], request=state["request"], kind=state.get("kind"),
            outcome=outcome, serving_tier=tier, model=model,
            verdict=state.get("verdict"), reasons=state.get("reasons", []),
            approved=state.get("approved"), code=state.get("code"), tests=state.get("tests"),
            exit_code=execution.get("exit_code"), timeout_s=self.settings.sandbox_timeout_s,
            output=execution.get("output"), run_quota=self.settings.run_quota,
            ticket_id=ticket_id, ticket_priority=state.get("ticket_priority"),
            ticket_sla_hours=state.get("ticket_sla_hours"),
            execution_reused=bool(execution.get("reused")),
            repairs_tried=tried, max_repairs=budget, repair_notes=state.get("repair_notes", []),
        ))
        self.store.save(RunRecord(
            run_id=state["run_id"], conversation_id=state["conversation_id"],
            created_at=state["created_at"], request=state["request"], kind=state.get("kind"),
            outcome=outcome, verdict=state.get("verdict"), reasons=state.get("reasons", []),
            approved=state.get("approved"), code=state.get("code"), tests=state.get("tests"),
            exit_code=execution.get("exit_code"), timed_out=bool(execution.get("timed_out")),
            output=execution.get("output"), serving_tier=tier, report=report,
            request_key=state.get("request_key"),
        ))
        return {**escalated, **counts, "outcome": outcome, "report": report}
