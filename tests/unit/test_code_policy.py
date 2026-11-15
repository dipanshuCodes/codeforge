import pytest

from codeforge.policy.code_policy import (
    PolicyDecision,
    defines_function,
    evaluate_code_policy,
    strictest,
)


def test_parse_failure_denies():
    d = evaluate_code_policy("def f(:\n")
    assert d.verdict == "deny"
    assert any("parse" in r for r in d.reasons)


def test_null_byte_denies():
    assert evaluate_code_policy("x = 1\x00").verdict == "deny"


def _v(source):
    return evaluate_code_policy(source).verdict


# --- allow ------------------------------------------------------------------------------

def test_pure_function_is_allowed():
    d = evaluate_code_policy("def is_palindrome(s):\n    return s == s[::-1]\n")
    assert d.verdict == "allow"


@pytest.mark.parametrize("source", [
    "import math\nfrom collections import Counter\nimport itertools, functools, re\n",
    "from solution import add\nimport pytest\n\ndef test_x():\n    with pytest.raises(ValueError):\n        add(-1)\n",
    "from typing import List\nfrom dataclasses import dataclass\nfrom functools import reduce\n",
    "import json, string, heapq, bisect, statistics, decimal, fractions, datetime\n",
    "if __name__ == '__main__':\n    print(1)\n",
])
def test_standard_pure_modules_pytest_and_solution_are_allowed(source):
    assert _v(source) == "allow"


@pytest.mark.parametrize("source", [
    "def remove(items, x):\n    items.remove(x)\n",       # .remove is a list method, not os.remove
    "def delete_all(d):\n    d.clear()\n",
    "def system(x):\n    return x\n",                    # a function merely named like a risky one
    "s = 'import os; os.system(\"rm -rf /\")'\n",       # risky text in a string is just data
])
def test_risky_looking_code_is_allowed(source):
    assert _v(source) == "allow"


# --- needs approval -----------------------------------------------------------------------

@pytest.mark.parametrize("source", [
    "def read(p):\n    with open(p) as f:\n        return f.read()\n",
    "from pathlib import Path\n",
    "import socket\n",
    "import urllib.request\n",
    "from http import client\n",
    "import requests\n",
])
def test_file_and_network_access_need_approval(source):
    d = evaluate_code_policy(source)
    assert d.verdict == "needs_approval"
    assert d.reasons


# --- deny ---------------------------------------------------------------------------------

@pytest.mark.parametrize("module", ["os", "sys", "subprocess", "shutil", "ctypes", "importlib",
                                    "builtins", "os.path"])
def test_dangerous_modules_are_denied(module):
    assert _v(f"import {module}\n") == "deny"
    assert _v(f"from {module} import *\n") == "deny"


@pytest.mark.parametrize("name", ["eval", "exec", "compile", "__import__"])
def test_dynamic_execution_is_denied(name):
    d = evaluate_code_policy(f"x = {name}('1')\n")
    assert d.verdict == "deny"
    assert any(name in r for r in d.reasons)


def test_dynamic_execution_denied_even_without_a_call():
    assert _v("f = eval\n") == "deny"


@pytest.mark.parametrize("source", [
    # Dunder attribute access (e.g. `.__class__`, `.__globals__`) is no longer denied: docs/adr/0001.
    "b = __builtins__\n",
    "getattr(__import__('os'), 'system')('ls')\n",
    "getattr(x, '__class__')\n",
    "getattr(x, name)\n",          # attribute name not known at check time
    "globals()['x'] = 1\n",
    "vars()\n",
])
def test_dunder_and_reflection_access_is_denied(source):
    assert _v(source) == "deny"


@pytest.mark.parametrize("module", ["numpy", "tempfile", "pickle", "multiprocessing", "signal"])
def test_anything_not_listed_is_denied(module):
    d = evaluate_code_policy(f"import {module}\n")
    assert d.verdict == "deny"
    assert any(module in r for r in d.reasons)


def test_relative_import_is_denied():
    assert _v("from . import x\n") == "deny"


def test_student_b_delete_home_folder_is_denied():
    code = (
        "import os, shutil\n\n"
        "def wipe_home():\n"
        "    home = os.path.expanduser('~')\n"
        "    for name in os.listdir(home):\n"
        "        shutil.rmtree(os.path.join(home, name), ignore_errors=True)\n"
    )
    d = evaluate_code_policy(code)
    assert d.verdict == "deny"
    assert any("os" in r for r in d.reasons) and any("shutil" in r for r in d.reasons)


def test_deny_wins_over_needs_approval_in_one_file():
    assert _v("import socket\nimport os\n") == "deny"


def test_strictest_prefers_deny():
    a = PolicyDecision(verdict="needs_approval", reasons=["a"])
    b = PolicyDecision(verdict="deny", reasons=["b"])
    d = strictest(a, b)
    assert d.verdict == "deny"
    assert d.reasons == ["a", "b"]


def test_strictest_allow_only_when_all_allow():
    allow = PolicyDecision(verdict="allow", reasons=[])
    approve = PolicyDecision(verdict="needs_approval", reasons=["x"])
    assert strictest(allow, allow).verdict == "allow"
    assert strictest(allow, approve).verdict == "needs_approval"


def test_defines_function():
    assert defines_function("def add(a, b): return a+b", "add")
    assert not defines_function("def add(a, b): return a+b", "sub")
    assert not defines_function("def outer():\n    def add(): pass\n", "add")
    assert not defines_function("def add(:", "add")


def test_deeply_nested_source_denies_without_crashing():
    # Under the size cap; older Pythons raise RecursionError in ast.parse, newer ones parse
    # it, so the nesting limit must deny it either way.
    assert evaluate_code_policy("a" + ".b" * 40_000).verdict == "deny"
    assert evaluate_code_policy("-" * 90_000 + "1").verdict == "deny"


def test_oversized_source_denies():
    d = evaluate_code_policy("x = 1\n" * 30_000)  # ~180 KB
    assert d.verdict == "deny"
    assert any("too large" in r for r in d.reasons)


def test_lone_surrogate_denies():
    # Valid in JSON ("\ud800") but cannot be written as UTF-8 for the sandbox.
    d = evaluate_code_policy("x = '\ud800'\n")
    assert d.verdict == "deny"


def test_defines_function_survives_pathological_source():
    assert defines_function("a" + ".b" * 40_000, "f") is False
