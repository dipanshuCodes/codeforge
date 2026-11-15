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


def test_valid_code_needs_approval():
    d = evaluate_code_policy("def is_palindrome(s):\n    return s == s[::-1]\n")
    assert d.verdict == "needs_approval"
    assert any("approval" in r for r in d.reasons)


def test_risky_looking_code_still_only_needs_approval():
    # The L1 stub has no allowlist yet; the R2 allowlist will deny this.
    assert evaluate_code_policy("import os\n").verdict == "needs_approval"


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
    # Under the size cap, yet ast.parse raises RecursionError / MemoryError on these.
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
