"""Sandboxed Execution: run generated code + tests with pytest in a separate process.

Limits: isolated interpreter (-I), fresh temp dir, hard timeout that kills the whole process
group, stripped environment (no secrets), output capped. Inside the child, an audit hook set
before pytest starts blocks the network, process spawning and writes outside the temp dir,
and RLIMIT_AS caps memory. Audit hooks can't be removed once added. These limits hold
whatever the policy verdict was: approval allows execution, never a looser sandbox.

macOS does not enforce RLIMIT_AS, so the memory cap applies on Linux (CI) only; elsewhere
the timeout is the backstop.
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
DEFAULT_MEMORY_LIMIT = 256 * 1024 * 1024

# Runs in the child as `python -I -B -c _BOOTSTRAP <memory limit> <pytest args...>`.
_BOOTSTRAP = """
import os, sys
ROOT = os.path.realpath(os.getcwd())
limit = int(sys.argv[1])
try:
    import resource
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
except (ImportError, ValueError, OSError) as exc:
    if sys.platform != "darwin":  # fail closed where the cap is expected to work
        print(f"sandbox: could not set the memory cap: {exc}", file=sys.stderr)
        sys.exit(3)

_SPAWN = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
          "os.fork", "os.forkpty", "pty.spawn")
_PATH_EVENTS = ("os.remove", "os.rmdir", "os.mkdir", "os.rename", "os.replace", "os.chmod",
                "os.chown", "os.truncate", "os.symlink", "os.link", "shutil.rmtree")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_realpath, _fspath = os.path.realpath, os.fsdecode
_DEVNULL = _realpath(os.devnull)

def _inside(path):
    if isinstance(path, int):
        return True  # an already-open file descriptor
    real = _realpath(_fspath(path))
    # pytest's logging plugin opens os.devnull for writing; discarding output is harmless.
    return real in (ROOT, _DEVNULL) or real.startswith(ROOT + os.sep)

def _hook(event, args):
    if event.startswith("socket."):
        raise PermissionError("network access is blocked by the CodeForge sandbox")
    if event in _SPAWN:
        raise PermissionError("starting processes is blocked by the CodeForge sandbox")
    if event == "open":
        path, mode, flags = args
        writing = any(c in (mode or "") for c in "wax+") or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing and path is not None and not _inside(path):
            raise PermissionError("writing outside the sandbox temp dir is blocked")
    elif event in _PATH_EVENTS:
        for path in args[:2]:
            if isinstance(path, (str, bytes, os.PathLike)) and not _inside(path):
                raise PermissionError("changing files outside the sandbox temp dir is blocked")

sys.addaudithook(_hook)
import pytest
sys.exit(pytest.main(sys.argv[2:]))
"""


class ExecutionResult(BaseModel):
    exit_code: int | None
    timed_out: bool
    output: str


def run_pytest(
    code: str, tests: str, *, timeout_s: float, max_output_bytes: int,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT,
) -> ExecutionResult:
    """Run `tests` against `code` (saved as solution.py) and return the real pytest result."""
    with tempfile.TemporaryDirectory(prefix="codeforge-") as tmp, tempfile.TemporaryFile() as out:
        Path(tmp, f"{SOLUTION_MODULE}.py").write_text(code, encoding="utf-8")
        Path(tmp, TEST_FILE).write_text(tests, encoding="utf-8")
        # Only what pytest needs; never the parent's env (it holds GROQ_API_KEY).
        # TMPDIR keeps pytest's tmp_path inside the temp dir, where writes are allowed.
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "TMPDIR": tmp}
        # -B: no .pyc writes, so nothing is written outside the temp dir.
        cmd = [sys.executable, "-I", "-B", "-c", _BOOTSTRAP, str(memory_limit_bytes),
               "-q", "-p", "no:cacheprovider", TEST_FILE]
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
