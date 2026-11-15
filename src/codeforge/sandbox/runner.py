"""Sandboxed Execution: run generated code + tests with pytest in a separate process.

L1 limits: isolated interpreter (-I), fresh temp dir, hard timeout that kills the whole
process group, stripped environment (no secrets), output capped. R2 adds the network block,
memory cap and Execution key.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

SOLUTION_MODULE = "solution"
TEST_FILE = f"test_{SOLUTION_MODULE}.py"


class ExecutionResult(BaseModel):
    exit_code: int | None
    timed_out: bool
    output: str


def run_pytest(code: str, tests: str, *, timeout_s: float, max_output_bytes: int) -> ExecutionResult:
    """Run `tests` against `code` (saved as solution.py) and return the real pytest result."""
    with tempfile.TemporaryDirectory(prefix="codeforge-") as tmp, tempfile.TemporaryFile() as out:
        Path(tmp, f"{SOLUTION_MODULE}.py").write_text(code, encoding="utf-8")
        Path(tmp, TEST_FILE).write_text(tests, encoding="utf-8")
        # Only what pytest needs; never the parent's env (it holds GROQ_API_KEY).
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp}
        cmd = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", TEST_FILE]
        proc = subprocess.Popen(
            cmd, cwd=tmp, env=env, stdin=subprocess.DEVNULL, stdout=out,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        timed_out = False
        try:
            exit_code: int | None = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
        # Kill the whole group either way: children may outlive pytest.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        out.seek(0)
        output = out.read(max_output_bytes).decode("utf-8", errors="replace")
    return ExecutionResult(exit_code=exit_code, timed_out=timed_out, output=output)
