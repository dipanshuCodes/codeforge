import pytest

from codeforge.policy.repair import (
    count_assertions,
    count_tests,
    evaluate_repair,
    should_repair,
)

CODE = "def double(x):\n    return x + x\n"
FIXED_CODE = "def double(x):\n    return 2 * x\n"

TESTS = (
    "from solution import double\n"
    "def test_one():\n    assert double(1) == 2\n"
    "def test_two():\n    assert double(2) == 4\n"
)


# --- counting -----------------------------------------------------------------------------

def test_count_tests_counts_functions_and_class_methods():
    src = (
        "def test_a(): pass\n"
        "def helper(): pass\n"
        "class TestX:\n    def test_b(self): pass\n    def other(self): pass\n"
        "class Helper:\n    def test_not_collected(self): pass\n"
    )
    assert count_tests(src) == 2


def test_count_assertions_ignores_constant_asserts():
    src = "def test_a():\n    assert True\n    assert 1\n    assert f() == 1\n"
    assert count_assertions(src) == 1


def test_count_assertions_counts_pytest_raises():
    src = (
        "import pytest\n"
        "def test_a():\n    with pytest.raises(ValueError):\n        f()\n"
    )
    assert count_assertions(src) == 1


def test_count_on_unparsable_source_is_zero():
    assert count_tests("def (") == 0
    assert count_assertions("def (") == 0


def test_parametrize_counts_as_one_test_known_gap():
    # Decided: a shrunken parametrize list is not caught (plan 07, UNRESOLVED section).
    many = "@pytest.mark.parametrize('x', [1, 2, 3, 4])\ndef test_a(x):\n    assert f(x)\n"
    few = "@pytest.mark.parametrize('x', [1])\ndef test_a(x):\n    assert f(x)\n"
    assert count_tests(many) == count_tests(few) == 1
    assert count_assertions(many) == count_assertions(few) == 1


# --- evaluate_repair: accepted ------------------------------------------------------------

def test_code_only_repair_1_is_accepted():
    decision = evaluate_repair(1, CODE, TESTS, FIXED_CODE, TESTS)
    assert decision.accepted
    assert decision.reasons == []


def test_repair_2_may_add_a_test():
    new_tests = TESTS + "def test_three():\n    assert double(3) == 6\n"
    assert evaluate_repair(2, CODE, TESTS, FIXED_CODE, new_tests).accepted


def test_repair_2_may_change_a_wrong_expectation_without_losing_tests():
    wrong = TESTS.replace("== 4", "== 5")
    assert evaluate_repair(2, CODE, wrong, FIXED_CODE, TESTS).accepted


# --- evaluate_repair: rejected ------------------------------------------------------------

def test_repair_that_deletes_a_failing_test_is_rejected():
    fewer = "from solution import double\ndef test_one():\n    assert double(1) == 2\n"
    decision = evaluate_repair(2, CODE, TESTS, FIXED_CODE, fewer)
    assert not decision.accepted
    assert any("tests" in r for r in decision.reasons)


def test_repair_that_drops_an_assertion_is_rejected():
    fewer = TESTS.replace("    assert double(2) == 4\n", "    pass\n")
    decision = evaluate_repair(2, CODE, TESTS, FIXED_CODE, fewer)
    assert not decision.accepted
    assert any("assertion" in r for r in decision.reasons)


def test_replacing_a_real_assert_with_assert_true_is_rejected():
    weaker = TESTS.replace("assert double(2) == 4", "assert True")
    assert not evaluate_repair(2, CODE, TESTS, FIXED_CODE, weaker).accepted


@pytest.mark.parametrize("marker", [
    "@pytest.mark.skip\n",
    "@pytest.mark.skipif(True, reason='x')\n",
    "@pytest.mark.xfail\n",
])
def test_repair_2_adding_skip_or_xfail_is_rejected(marker):
    weaker = "import pytest\n" + TESTS.replace("def test_two", marker + "def test_two")
    decision = evaluate_repair(2, CODE, TESTS, FIXED_CODE, weaker)
    assert not decision.accepted
    assert any("skip" in r or "xfail" in r for r in decision.reasons)


def test_repair_2_calling_pytest_skip_is_rejected():
    weaker = "import pytest\n" + TESTS.replace(
        "    assert double(2) == 4\n", "    pytest.skip('later')\n    assert double(2) == 4\n")
    assert not evaluate_repair(2, CODE, TESTS, FIXED_CODE, weaker).accepted


def test_existing_skip_marker_is_not_a_new_skip():
    base = "import pytest\n" + TESTS.replace("def test_two", "@pytest.mark.skip\ndef test_two")
    assert evaluate_repair(2, CODE, base, FIXED_CODE, base).accepted


def test_repair_1_may_not_touch_the_tests():
    changed = TESTS.replace("== 4", "== 5")
    decision = evaluate_repair(1, CODE, TESTS, FIXED_CODE, changed)
    assert not decision.accepted
    assert any("code only" in r for r in decision.reasons)


def test_unchanged_code_is_rejected():
    decision = evaluate_repair(1, CODE, TESTS, CODE, TESTS)
    assert not decision.accepted
    assert any("unchanged" in r for r in decision.reasons)


def test_unparsable_repair_is_rejected():
    assert not evaluate_repair(1, CODE, TESTS, "def (", TESTS).accepted
    assert not evaluate_repair(2, CODE, TESTS, FIXED_CODE, "def (").accepted


def test_unparsable_old_tests_fail_closed():
    assert not evaluate_repair(2, CODE, "def (", FIXED_CODE, TESTS).accepted


# --- should_repair ------------------------------------------------------------------------

@pytest.mark.parametrize("outcome, expected", [
    ("tests_failed", True),
    ("tests_passed", False),
    ("timed_out", False),
    ("denied", False),
    ("rejected", False),
    ("cannot_generate", False),
    ("unsupported", False),
    ("quota_exceeded", False),
    (None, False),
])
def test_should_repair_by_outcome(outcome, expected):
    assert should_repair(outcome, repairs_tried=0, max_attempts=2, serving_tier="primary") is expected


def test_should_repair_stops_at_the_budget():
    assert should_repair("tests_failed", 1, 2, "primary")
    assert not should_repair("tests_failed", 2, 2, "primary")
    assert not should_repair("tests_failed", 0, 0, "primary")


def test_should_repair_never_on_template_tier():
    assert not should_repair("tests_failed", 0, 2, "template")


def test_should_repair_allows_fallback_tier():
    assert should_repair("tests_failed", 0, 2, "fallback")


def test_repair_2_may_fix_a_wrong_test_and_leave_the_code_alone():
    wrong = TESTS.replace("== 4", "== 5")
    assert evaluate_repair(2, FIXED_CODE, wrong, FIXED_CODE, TESTS).accepted
