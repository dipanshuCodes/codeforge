"""Hand-written fixtures, run only through the sandbox itself."""

import os
import re
import sys
import time

import pytest

from codeforge.sandbox.runner import run_pytest

LIMITS = dict(timeout_s=10, max_output_bytes=10_240)
ADD = "def add(a, b):\n    return a + b\n"


def test_passing_tests_exit_0():
    tests = "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    r = run_pytest(ADD, tests, **LIMITS)
    assert r.exit_code == 0
    assert r.timed_out is False
    assert "1 passed" in r.output


def test_failing_tests_exit_1():
    tests = "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 6\n"
    assert run_pytest(ADD, tests, **LIMITS).exit_code == 1


def test_no_tests_exit_5():
    assert run_pytest(ADD, "x = 1\n", **LIMITS).exit_code == 5


def test_infinite_loop_times_out():
    start = time.monotonic()
    r = run_pytest("while True:\n    pass\n", "import solution\n", timeout_s=1, max_output_bytes=10_240)
    assert r.timed_out is True
    assert r.exit_code is None
    assert time.monotonic() - start < 5


def test_spawning_a_process_is_blocked():
    # A child process would escape the in-process network block, so none may start.
    # (The process-group kill on timeout stays as a second layer.)
    tests = (
        "import subprocess, pytest\n\n"
        "def test_spawn():\n"
        "    with pytest.raises(PermissionError, match='sandbox'):\n"
        "        subprocess.Popen(['sleep', '30'])\n"
    )
    r = run_pytest(ADD, tests, **LIMITS)
    assert r.exit_code == 0, r.output


def test_network_is_blocked():
    tests = (
        "import socket, pytest\n\n"
        "def test_socket():\n"
        "    with pytest.raises(PermissionError, match='network'):\n"
        "        socket.create_connection(('127.0.0.1', 9), timeout=1)\n"
    )
    r = run_pytest(ADD, tests, **LIMITS)
    assert r.exit_code == 0, r.output


def test_writes_outside_the_temp_dir_are_blocked(tmp_path):
    target = tmp_path / "escape.txt"
    tests = (
        "import pytest\n\n"
        "def test_write():\n"
        "    with pytest.raises(PermissionError, match='outside'):\n"
        f"        open({str(target)!r}, 'w')\n"
    )
    r = run_pytest(ADD, tests, **LIMITS)
    assert r.exit_code == 0, r.output
    assert not target.exists()


def test_writes_inside_the_temp_dir_and_tmp_path_work():
    tests = (
        "def test_write(tmp_path):\n"
        "    open('local.txt', 'w').write('ok')\n"
        "    (tmp_path / 'f.txt').write_text('ok')\n"
        "    assert open('local.txt').read() == 'ok'\n"
    )
    r = run_pytest(ADD, tests, **LIMITS)
    assert r.exit_code == 0, r.output


def test_env_is_stripped(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_FAKEFAKEFAKEFAKEFAKE")
    tests = "import os\n\ndef test_env():\n    assert 'GROQ_API_KEY' not in os.environ\n"
    assert run_pytest(ADD, tests, **LIMITS).exit_code == 0


def test_output_truncated_and_non_utf8_safe():
    # Printed inside a failing test, so pytest shows the captured bytes in its report.
    tests = (
        "import sys\n\ndef test_x():\n"
        "    sys.stdout.buffer.write(b'\\xff' * 50_000)\n    sys.stdout.flush()\n    assert False\n"
    )
    r = run_pytest(ADD, tests, **LIMITS)
    assert r.exit_code == 1
    assert len(r.output) >= 1_000
    assert len(r.output.encode()) <= 10_240 * 3


def test_temp_dir_removed():
    tests = "import os\n\ndef test_x():\n    print('CWD=' + os.getcwd())\n    assert False\n"
    r = run_pytest(ADD, tests, timeout_s=10, max_output_bytes=10_240)
    m = re.search(r"CWD=(\S+)", r.output)
    assert m, r.output
    assert not os.path.exists(m.group(1))
