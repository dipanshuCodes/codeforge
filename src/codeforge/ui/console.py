"""Console adapter: the primary interface. Holds no logic the graph doesn't own."""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.types import Command

APPROVAL_PROMPT = "Type 'approve' to run it; anything else rejects: "
QUIT = "/quit"
BAD = "/bad"  # thumbs-down on the last Run: "/bad [reason]"
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
    store: Any = None,
) -> None:
    """Read Requests until /quit or EOF; pause for the Approver when the graph interrupts.

    `/bad [reason]` stores Feedback on the last Run of this Conversation (needs `store`)."""
    config = {"configurable": {"thread_id": conversation_id}}
    last_run_id: str | None = None
    while True:
        try:
            text = input_fn("\nRequest> ")
        except EOFError:
            return
        if text.strip() == QUIT:
            return
        if not text.strip():
            continue
        if text.strip().split()[0] == BAD:
            feedback_id = (store.add_feedback(last_run_id, text.strip()[len(BAD):].strip())
                           if store is not None and last_run_id else None)
            print_fn(f"Feedback saved: {feedback_id} (promote with: codeforge feedback promote "
                     f"{feedback_id})" if feedback_id else "No Run yet to give Feedback on.")
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
        last_run_id = result.get("run_id")


def promote_feedback(settings: Any, feedback_id: str, drafts_dir: Path) -> Path | None:
    """Write a draft Golden case for the config User's Feedback; None if it isn't theirs."""
    from codeforge.runs.feedback import draft_golden_case
    from codeforge.runs.store import RunStore

    store = RunStore(settings)
    feedback = store.get_feedback(feedback_id)
    run = store.get(feedback.run_id) if feedback else None
    if run is None:
        return None
    case = draft_golden_case(feedback, run)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"{case['id']}.json"
    path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from codeforge.config import ConfigError, load_env_files, load_settings
    from codeforge.graph.build import build_graph
    from codeforge.llm.factory import build_caller
    from codeforge.runs.store import RunStore

    load_env_files(Path.cwd())  # .env.local (local) / .env (deployed); the shell still wins
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(2)
    args = sys.argv[1:] if argv is None else argv
    if args[:2] == ["feedback", "promote"]:
        if len(args) != 3:
            print("usage: codeforge feedback promote <feedback id>", file=sys.stderr)
            sys.exit(2)
        path = promote_feedback(settings, args[2], Path.cwd() / "evals" / "drafts")
        if path is None:
            print("Feedback not found.", file=sys.stderr)  # missing and not yours look alike
            sys.exit(1)
        print(f"Draft Golden case written: {path}\nWrite its expected outcome, then move it "
              "into evals/golden_set.json (red), fix, and see it pass (green).")
        return
    if not os.environ.get("GROQ_API_KEY"):
        print("Config error: GROQ_API_KEY is not set", file=sys.stderr)
        sys.exit(2)
    store = RunStore(settings)
    graph = build_graph(settings, build_caller(settings), store, checkpointer=MemorySaver())
    print(DEV_WARNING)
    print(f"User: {settings.user_id} ({settings.role}). Type {QUIT} to exit, {BAD} [reason] "
          "to flag the last Run.")
    run_console(graph, input_fn=input, print_fn=print, conversation_id=uuid.uuid4().hex,
                store=store)
