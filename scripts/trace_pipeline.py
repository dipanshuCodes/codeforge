"""Trace the real pipeline node by node. Rejects at the approval gate, so nothing executes."""
import os
import sys
import uuid
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.config import ConfigError, load_env_files, load_settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import GroqCaller, ModelCallError
from codeforge.runs.store import RunStore

REQUEST = sys.argv[1] if len(sys.argv) > 1 else (
    "If I pass a list, return its sum using a list comprehension; "
    "if a tuple, use functional programming"
)


class TracingCaller:
    def __init__(self, inner):
        self.inner = inner

    def call(self, schema, system, user):
        name = schema.__name__
        try:
            out = self.inner.call(schema, system, user)
        except ModelCallError as exc:
            cause = exc.__cause__
            print(f"  [model:{name}] FAIL {type(exc).__name__}({exc}) "
                  f"cause={type(cause).__name__ if cause else None}: {str(cause)[:300] if cause else ''}")
            raise
        print(f"  [model:{name}] OK {str(out.model_dump())[:200]}")
        return out


load_env_files(Path.cwd())
try:
    settings = load_settings()
except ConfigError as exc:
    sys.exit(f"Config error: {exc}")
print("GROQ_API_KEY present:", bool(os.environ.get("GROQ_API_KEY")))
print("model:", settings.secondary_model, "| timeout:", settings.sandbox_timeout_s)

graph = build_graph(settings, TracingCaller(GroqCaller(settings.secondary_model)),
                    RunStore(settings), checkpointer=MemorySaver())
cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}


def run(inp):
    for chunk in graph.stream(inp, cfg, stream_mode="updates"):
        for node, delta in chunk.items():
            if node == "__interrupt__":
                print("== INTERRUPT (approval gate reached) ==")
                continue
            keys = {k: (str(v)[:120] if v is not None else None) for k, v in (delta or {}).items()
                    if k not in ("raw_text",)}
            print(f"== {node}: {keys}")


run({"raw_text": REQUEST})
snap = graph.get_state(cfg)
if snap.next:  # paused at approval
    print("paused before:", snap.next, "-> rejecting")
    run(Command(resume="reject"))
final = graph.get_state(cfg).values
print("\nFINAL outcome:", final.get("outcome"), "| verdict:", final.get("verdict"),
      "| reasons:", final.get("reasons"))
