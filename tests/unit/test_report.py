from codeforge.reporting.report import ReportInput, render_report

CODE = "def is_palindrome(s):\n    return s == s[::-1]\n"
TESTS = "from solution import is_palindrome\n\ndef test_p():\n    assert is_palindrome('aba')\n"


def _input(**overrides) -> ReportInput:
    base = dict(
        run_id="3f2a91deadbeef",
        request="Write a palindrome checker",
        kind="python_function",
        outcome="tests_passed",
        serving_tier="primary",
        model="openai/gpt-oss-120b",
        verdict="needs_approval",
        reasons=["L1 policy stub"],
        approved=True,
        code=CODE,
        tests=TESTS,
        exit_code=0,
        timeout_s=10.0,
        output="RAW-PYTEST-OUTPUT\n1 passed in 0.01s\n",
    )
    base.update(overrides)
    return ReportInput(**base)


def test_passed_report():
    text = render_report(_input())
    assert "Run 3f2a91 · TESTS PASSED" in text
    assert "openai/gpt-oss-120b" in text
    assert "Write a palindrome checker" in text
    assert "pytest exit 0" in text
    assert '"1 passed in 0.01s"' in text
    assert "approved at console" in text
    assert CODE.strip() in text
    assert "RAW-PYTEST-OUTPUT" not in text


def test_failed_report_shows_output():
    text = render_report(_input(outcome="tests_failed", exit_code=1))
    assert "TESTS FAILED" in text
    assert "TESTS PASSED" not in text
    assert "RAW-PYTEST-OUTPUT" in text


def test_exit5_report():
    text = render_report(_input(outcome="tests_failed", exit_code=5))
    assert "TESTS DID NOT RUN CLEANLY (pytest exit 5)" in text
    assert "TESTS PASSED" not in text
    assert "RAW-PYTEST-OUTPUT" in text


def test_timeout_report():
    text = render_report(_input(outcome="timed_out", exit_code=None))
    assert "TIMED OUT after 10s" in text


def test_denied_report_lists_reasons():
    text = render_report(
        _input(outcome="denied", verdict="deny", reasons=["could not parse the source"],
               approved=None, exit_code=None, output=None)
    )
    assert "DENIED" in text
    assert "could not parse the source" in text


def test_rejected_report():
    text = render_report(_input(outcome="rejected", approved=False, exit_code=None, output=None))
    assert "REJECTED by the approver" in text


def test_unsupported_report_has_no_code_section():
    text = render_report(
        _input(outcome="unsupported", kind="sql_query", verdict=None, reasons=[], approved=None,
               code=None, tests=None, exit_code=None, output=None, serving_tier=None)
    )
    assert "NOT SUPPORTED" in text
    assert "── code ──" not in text
    assert "Serving tier" not in text


def test_cannot_generate_report():
    text = render_report(
        _input(outcome="cannot_generate", verdict=None, reasons=[], approved=None,
               code=None, tests=None, exit_code=None, output=None)
    )
    assert "CANNOT GENERATE NOW" in text


def test_exit0_without_pass_report():
    text = render_report(_input(outcome="tests_failed", exit_code=0, output="1 skipped in 0.01s\n"))
    assert "NO TEST PASSED (pytest exit 0)" in text
    assert "TESTS PASSED" not in text
