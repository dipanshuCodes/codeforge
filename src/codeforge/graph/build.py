"""Wire the L1 graph. Every conditional edge routes on a typed field, never on text."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from codeforge.config import Settings
from codeforge.graph.nodes import Nodes
from codeforge.graph.state import RunState
from codeforge.llm.caller import StructuredCaller
from codeforge.policy.repair import should_repair
from codeforge.reporting.outcome import outcome_from_execution
from codeforge.runs.store import RunStore
from codeforge.sandbox.runner import ExecutionResult, run_pytest


def _continue_or_report(next_node: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return "report" if state.get("outcome") else next_node
    return route


def _after_ingress(state: RunState) -> str:
    if state.get("duplicate_of"):
        return END  # the stored Run's report is already in state
    return "report" if state.get("outcome") else "triage"


def _after_policy(state: RunState) -> str:
    verdict = state.get("verdict")
    if verdict == "allow":
        return "execute"
    if verdict == "needs_approval":
        return "approval"
    return "report"  # deny, or anything unexpected: fail closed


def _after_approval(state: RunState) -> str:
    return "execute" if state.get("approved") is True else "report"


def build_graph(
    settings: Settings,
    caller: StructuredCaller,
    store: RunStore,
    *,
    run_tests: Callable[..., ExecutionResult] = run_pytest,
    checkpointer: Any = None,
):
    nodes = Nodes(settings, caller, store, run_tests)

    def _wants_repair(state: RunState) -> bool:
        execution = state.get("execution") or {}
        outcome = state.get("outcome") or outcome_from_execution(
            execution.get("exit_code"), bool(execution.get("timed_out")), execution.get("output") or ""
        )
        return should_repair(outcome, state.get("repairs_tried", 0),
                             settings.max_repair_attempts, state.get("serving_tier"))

    def after_execute(state: RunState) -> str:
        return "repair" if _wants_repair(state) else "report"

    def after_repair(state: RunState) -> str:
        status = state.get("repair_status")
        if status == "proposed":
            return "policy"  # repaired code and tests are untrusted: back through the gate
        if status == "rejected" and _wants_repair(state):
            return "repair"  # a rejected attempt is spent; the next one may still run
        return "report"

    g = StateGraph(RunState)
    for name in ("ingress", "triage", "escalation", "router", "requirements", "codegen",
                 "testgen", "policy", "approval", "execute", "repair", "report"):
        g.add_node(name, getattr(nodes, name))

    g.add_edge(START, "ingress")
    g.add_conditional_edges("ingress", _after_ingress, ["triage", "report", END])
    g.add_edge("triage", "escalation")
    g.add_edge("escalation", "router")
    g.add_conditional_edges("router", _continue_or_report("requirements"), ["requirements", "report"])
    g.add_conditional_edges("requirements", _continue_or_report("codegen"), ["codegen", "report"])
    g.add_conditional_edges("codegen", _continue_or_report("testgen"), ["testgen", "report"])
    g.add_conditional_edges("testgen", _continue_or_report("policy"), ["policy", "report"])
    g.add_conditional_edges("policy", _after_policy, ["execute", "approval", "report"])
    g.add_conditional_edges("approval", _after_approval, ["execute", "report"])
    g.add_conditional_edges("execute", after_execute, ["repair", "report"])
    g.add_conditional_edges("repair", after_repair, ["policy", "repair", "report"])
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)
