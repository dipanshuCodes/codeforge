import pytest

from codeforge.reporting.outcome import outcome_from_execution, pytest_summary_line


@pytest.mark.parametrize(
    ("exit_code", "timed_out", "expected"),
    [
        (0, False, "tests_passed"),
        (1, False, "tests_failed"),
        (2, False, "tests_failed"),
        (5, False, "tests_failed"),
        (None, True, "timed_out"),
        (0, True, "timed_out"),
        (None, False, "tests_failed"),
    ],
)
def test_outcome_from_execution(exit_code, timed_out, expected):
    assert outcome_from_execution(exit_code, timed_out, "..\n2 passed in 0.01s\n") == expected


def test_summary_line_found():
    out = "..\n==== 2 passed in 0.01s ====\n"
    assert pytest_summary_line(out) == "2 passed in 0.01s"


def test_summary_line_quiet_mode():
    # `pytest -q` prints the summary without the === border.
    assert pytest_summary_line("..\n2 passed in 0.01s\n") == "2 passed in 0.01s"


def test_summary_line_missing():
    assert pytest_summary_line("no summary") is None


PASS_OUT = "..\n2 passed in 0.01s\n"


@pytest.mark.parametrize(
    "output",
    [
        "s\n1 skipped in 0.01s\n",            # every test skipped
        "",                                    # exited 0 before pytest printed anything
        "1 passed, 1 failed in 0.02s\n",       # cannot happen with exit 0, but never a pass
        "no tests ran in 0.01s\n",
    ],
)
def test_exit0_without_a_passing_test_is_not_a_pass(output):
    assert outcome_from_execution(0, False, output) == "tests_failed"


def test_exit0_with_passing_tests_is_a_pass():
    assert outcome_from_execution(0, False, PASS_OUT) == "tests_passed"
    assert outcome_from_execution(0, False, "3 passed, 1 skipped in 0.1s\n") == "tests_passed"
