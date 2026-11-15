
from pathlib import Path
import uuid

import gradio as gr
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codeforge.config import load_env_files, load_settings
from codeforge.graph.build import build_graph
from codeforge.llm.factory import build_caller
from codeforge.runs.store import RunStore


# Load project configuration
load_env_files(Path.cwd())
settings = load_settings()

# Build the CodeForge graph
graph = build_graph(
    settings,
    build_caller(settings),
    RunStore(settings),
    checkpointer=MemorySaver(),
)



def format_interrupt(result):
    interrupts = result.get("__interrupt__", ())

    if not interrupts:
        return "Approval is required."

    value = interrupts[0].value

    if not isinstance(value, dict):
        return str(value)

    reasons = value.get("reasons", [])
    code = value.get("code", "")
    tests = value.get("tests", "")

    reason_text = "\n".join(f"- {reason}" for reason in reasons)

    return f"""## Code review required

**Run ID:** `{value.get("run_id", "N/A")}`

**Serving tier:** {value.get("serving_tier", "Unknown")}

**Verdict:** {value.get("verdict", "needs_approval")}

### Why approval is required
{reason_text or "Manual approval required."}

### Generated code
```python
{code}
```

### Generated tests
```python
{tests}
```

**Review the code and tests, then select Approve or Reject.**
"""



def respond(message, history, thread_id):
    if not message.strip():
        return history, "", False

    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = graph.invoke({"raw_text": message}, config)

        # Only display the masked Request returned by the graph.
        masked_request = result.get("request", "[Request masked]")

        if "__interrupt__" in result:
            reply = format_interrupt(result)
            return (
                history + [
                    {"role": "user", "content": masked_request},
                    {"role": "assistant", "content": reply},
                ],
                "",
                True,
            )

        reply = result.get("report") or "The run finished, but no report was returned."

        return (
            history + [
                {"role": "user", "content": masked_request},
                {"role": "assistant", "content": str(reply)},
            ],
            "",
            False,
        )

    except Exception:
        return (
            history + [
                {"role": "user", "content": "[Request submitted]"},
                {
                    "role": "assistant",
                    "content": "CodeForge couldn't complete this request. Please try again.",
                },
            ],
            "",
            False,
        )



def resume_run(answer, history, thread_id):
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = graph.invoke(Command(resume=answer), config)

        if "__interrupt__" in result:
            reply = format_interrupt(result)
            return (
                history + [{"role": "assistant", "content": reply}],
                True,
            )

        reply = result.get("report") or "The run finished, but no report was returned."
        return (
            history + [{"role": "assistant", "content": str(reply)}],
            False,
        )

    except Exception:
        return (
            history + [{
                "role": "assistant",
                "content": "CodeForge couldn't complete this action. Please try again.",
            }],
            False,
        )


with gr.Blocks(title="CodeForge") as demo:
    gr.Markdown("# CodeForge")
    gr.Markdown("Describe the code you want. CodeForge will generate code, tests, and a test report.")

    thread_id = gr.State(lambda: str(uuid.uuid4()))
    approval_pending = gr.State(False)

    chatbot = gr.Chatbot(height=500)

    message = gr.Textbox(
        label="Your request",
        placeholder="Example: Write a Python function to check whether a number is prime.",
    )

    with gr.Row():
        submit = gr.Button("Generate", variant="primary")
        approve = gr.Button("Approve")
        reject = gr.Button("Reject")

    submit.click(
        respond,
        inputs=[message, chatbot, thread_id],
        outputs=[chatbot, message, approval_pending],
    )

    message.submit(
        respond,
        inputs=[message, chatbot, thread_id],
        outputs=[chatbot, message, approval_pending],
    )

    approve.click(
        lambda history, tid: resume_run("approve", history, tid),
        inputs=[chatbot, thread_id],
        outputs=[chatbot, approval_pending],
    )

    reject.click(
        lambda history, tid: resume_run("reject", history, tid),
        inputs=[chatbot, thread_id],
        outputs=[chatbot, approval_pending],
    )


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
