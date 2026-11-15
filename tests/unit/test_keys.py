from codeforge.runs.keys import execution_key, request_key


def test_request_key_is_stable_and_per_user():
    assert request_key("u-a", "add two numbers") == request_key("u-a", "add two numbers")
    assert request_key("u-a", "add two numbers") != request_key("u-b", "add two numbers")
    assert request_key("u-a", "add two numbers") != request_key("u-a", "add three numbers")


def test_request_key_fields_cannot_run_together():
    assert request_key("u-ab", "c") != request_key("u-a", "bc")


def test_execution_key_covers_user_code_and_tests():
    base = execution_key("u-a", "code", "tests")
    assert base == execution_key("u-a", "code", "tests")
    assert base != execution_key("u-b", "code", "tests")
    assert base != execution_key("u-a", "code2", "tests")
    assert base != execution_key("u-a", "code", "tests2")
    assert execution_key("u-a", "ab", "c") != execution_key("u-a", "a", "bc")
