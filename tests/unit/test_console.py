from langgraph.checkpoint.memory import MemorySaver

from codeforge.agents.schemas import CodeOutput, Param, Requirements, RouterOutput, TestsOutput
from codeforge.config import Settings
from codeforge.graph.build import build_graph
from codeforge.llm.caller import FakeCaller
from codeforge.runs.store import RunStore
from codeforge.ui.console import run_console

REQ = Requirements(function_name="is_palindrome", description="Palindrome check.",
                   params=[Param(name="s", type="str")], returns="bool", edge_cases=[])
# Reads a file, so the policy asks for approval and the console shows the prompt.
CODE = ("def is_palindrome(s):\n    return s == s[::-1]\n\n\n"
        "def load(path):\n    with open(path) as f:\n        return f.read()\n")
TESTS = "from solution import is_palindrome\n\ndef test_yes():\n    assert is_palindrome('aba')\n"


def _graph(tmp_path):
    settings = Settings(user_id="u-alice", role="student", db_path=str(tmp_path / "r.db"),
                        sandbox_timeout_s=5)
    caller = FakeCaller({RouterOutput: RouterOutput(kind="python_function"), Requirements: REQ,
                         CodeOutput: CodeOutput(code=CODE), TestsOutput: TestsOutput(tests=TESTS)})
    return build_graph(settings, caller, RunStore(settings), checkpointer=MemorySaver())


def _run(tmp_path, inputs):
    answers = iter(inputs)
    printed: list[str] = []

    def input_fn(prompt: str) -> str:
        printed.append(prompt)
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    run_console(_graph(tmp_path), input_fn=input_fn, print_fn=printed.append, conversation_id="c1")
    return "\n".join(printed)


def test_console_approve_flow(tmp_path):
    out = _run(tmp_path, ["palindrome please", "approve", "/quit"])
    assert "You (masked): palindrome please" in out
    assert "Type 'approve' to run it; anything else rejects: " in out
    assert "needs_approval" in out
    assert CODE.strip() in out
    assert "TESTS PASSED" in out


def test_console_empty_answer_rejects(tmp_path):
    out = _run(tmp_path, ["palindrome please", "", "/quit"])
    assert "REJECTED by the approver" in out
    assert "TESTS PASSED" not in out


def test_console_eof_at_approval_rejects(tmp_path):
    out = _run(tmp_path, ["palindrome please"])
    assert "REJECTED by the approver" in out


def test_console_eof_exits_cleanly(tmp_path):
    _run(tmp_path, [])


def test_console_blank_request_is_skipped(tmp_path):
    out = _run(tmp_path, ["   ", "/quit"])
    assert "You (masked)" not in out


def test_main_without_any_model_key_warns_and_still_starts(monkeypatch, tmp_path, capsys):
    from codeforge.ui import console

    monkeypatch.setenv("CODEFORGE_USER_ID", "u-dev")
    monkeypatch.setenv("CODEFORGE_ROLE", "student")
    monkeypatch.setenv("CODEFORGE_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env.local / .env here
    monkeypatch.setattr(console, "run_console", lambda *a, **k: None)
    console.main()  # must not exit: templates can still answer
    assert "only the template tier" in capsys.readouterr().err


def test_approval_display_escapes_control_characters(tmp_path):
    from codeforge.ui.console import _show_approval

    printed: list[str] = []
    hidden = "import os\r\x1b[2Kdef is_palindrome(s):\n\treturn s == s[::-1]\n"
    _show_approval({"verdict": "needs_approval", "reasons": [], "code": hidden, "tests": "x\x07"},
                   printed.append)
    out = "\n".join(printed)
    assert "\r" not in out and "\x1b" not in out and "\x07" not in out
    assert "\\r" in out and "\\x1b" in out and "\\x07" in out
    assert "\n\treturn" in out  # newlines and tabs are kept
