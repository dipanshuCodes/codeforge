"""Graph nodes. Agents propose; the deterministic code here decides and records."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from codeforge.agents.codegen import generate_code
from codeforge.agents.requirements import extract_requirements
from codeforge.agents.router import classify
from codeforge.agents.schemas import Requirements
from codeforge.agents.testgen import generate_tests
from codeforge.config import Settings
from codeforge.graph.state import RUN_DEFAULTS, RunState
from codeforge.llm.caller import ModelCallError, ModelOutputError, ModelUnavailableError, StructuredCaller
from codeforge.policy.code_policy import defines_function, evaluate_code_policy, strictest
from codeforge.policy.quota import NOT_COUNTED, quota_allows, quota_window_start
from codeforge.policy.resilience import degrade_verdict, worst_tier
from codeforge.policy.templates import pick_template
from codeforge.privacy.masking import mask
from codeforge.reporting.outcome import outcome_from_execution
from codeforge.reporting.report import ReportInput, render_report
from codeforge.runs.keys import execution_key, request_key
from codeforge.runs.store import RunRecord, RunStore
from codeforge.sandbox.runner import ExecutionResult

APPROVE_WORD = "approve"


class Nodes:
    def __init__(
        self,
        settings: Settings,
        caller: StructuredCaller,
        store: RunStore,
        run_tests: Callable[..., ExecutionResult],
    ) -> None:
        self.settings = settings
        self.caller = caller
        self.store = store
        self.run_tests = run_tests

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
        # L1 stub (R3 adds the model call).
        return {"triage": {"language": "en", "sentiment": "calm", "urgency": "low",
                           "wants_human": False}}

    def escalation(self, state: RunState) -> dict[str, Any]:
        # L1 stub (R3 adds the rules, Tickets and the P1 short-cut).
        return {"escalation": None}

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
        return {"outcome": "cannot_generate", "serving_tier": "template", "ticket_id": ticket_id}

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
        return update

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
            return {"approved": False, "outcome": "rejected"}
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

    # --- report --------------------------------------------------------------------------

    def report(self, state: RunState) -> dict[str, Any]:
        execution = state.get("execution") or {}
        outcome = state.get("outcome") or outcome_from_execution(
            execution.get("exit_code"), bool(execution.get("timed_out")), execution.get("output") or ""
        )
        tier = state.get("serving_tier") if state.get("code") is not None else None
        if state.get("ticket_id"):
            tier = state.get("serving_tier")  # name the tier even when nothing was generated
        model = {"primary": self.settings.large_model,
                 "fallback": self.settings.small_model}.get(tier or "")
        report = render_report(ReportInput(
            run_id=state["run_id"], request=state["request"], kind=state.get("kind"),
            outcome=outcome, serving_tier=tier, model=model,
            verdict=state.get("verdict"), reasons=state.get("reasons", []),
            approved=state.get("approved"), code=state.get("code"), tests=state.get("tests"),
            exit_code=execution.get("exit_code"), timeout_s=self.settings.sandbox_timeout_s,
            output=execution.get("output"), run_quota=self.settings.run_quota,
            ticket_id=state.get("ticket_id"),
            execution_reused=bool(execution.get("reused")),
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
        return {"outcome": outcome, "report": report}
