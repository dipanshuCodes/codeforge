"""Console adapter: the primary interface. Holds no logic the graph doesn't own."""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable
from typing import Any

from langgraph.types import Command

APPROVAL_PROMPT = "Type 'approve' to run it; anything else rejects: "
QUIT = "/quit"
DEV_WARNING = (
    "CodeForge — developers only. The full sandbox and policy allowlist (R2) are not built yet."
)


def _visible(text: str) -> str:
    """Escape control characters (except newline and tab) so model text can't hide lines
    from the Approver with carriage returns or terminal escape codes."""
    return "".join(
        ch if ch in "\n\t" or (ch.isprintable() and ch != "\x7f") else repr(ch)[1:-1]
        for ch in text
    )


def _show_approval(payload: dict[str, Any], print_fn: Callable[[str], None]) -> None:
    print_fn(f"Policy verdict: {payload['verdict']}")
    for reason in payload.get("reasons", []):
        print_fn(f"  - {_visible(reason)}")
    print_fn("── code ──\n" + _visible((payload.get("code") or "").rstrip()))
    print_fn("── tests ──\n" + _visible((payload.get("tests") or "").rstrip()))


def run_console(
    graph: Any,
    *,
    input_fn: Callable[[str], str],
    print_fn: Callable[[str], None],
    conversation_id: str,
) -> None:
    """Read Requests until /quit or EOF; pause for the Approver when the graph interrupts."""
    config = {"configurable": {"thread_id": conversation_id}}
    while True:
        try:
            text = input_fn("\nRequest> ")
        except EOFError:
            return
        if text.strip() == QUIT:
            return
        if not text.strip():
            continue
        result = graph.invoke({"raw_text": text}, config)
        print_fn(f"You (masked): {result.get('request', '')}")
        while "__interrupt__" in result:
            _show_approval(result["__interrupt__"][0].value, print_fn)
            try:
                answer = input_fn(APPROVAL_PROMPT)
            except EOFError:
                answer = ""  # no answer is never approval
            result = graph.invoke(Command(resume=answer), config)
        print_fn(result.get("report") or "")


def main() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from pathlib import Path

    from codeforge.config import ConfigError, load_env_files, load_settings
    from codeforge.graph.build import build_graph
    from codeforge.llm.factory import build_caller, build_summary_caller
    from codeforge.runs.store import RunStore

    load_env_files(Path.cwd())  # .env.local (local) / .env (deployed); the shell still wins
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(2)
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GROQ_API_KEY")):
        # Not fatal: tiers without a key are skipped; with none, only Templates can answer.
        print("Warning: no model API key set; only the template tier can answer.", file=sys.stderr)
    graph = build_graph(settings, build_caller(settings), RunStore(settings),
                        checkpointer=MemorySaver(), summary_caller=build_summary_caller(settings))
    print(DEV_WARNING)
    print(f"User: {settings.user_id} ({settings.role}). Type {QUIT} to exit.")
    run_console(graph, input_fn=input, print_fn=print, conversation_id=uuid.uuid4().hex)
