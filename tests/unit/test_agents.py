import pytest

from codeforge.agents.codegen import generate_code
from codeforge.agents.requirements import extract_requirements
from codeforge.agents.router import classify
from codeforge.agents.schemas import CodeOutput, Param, Requirements, RouterOutput, TestsOutput
from codeforge.agents.testgen import generate_tests
from codeforge.llm.caller import FakeCaller, ModelOutputError

REQ = Requirements(
    function_name="is_palindrome",
    description="Check whether a string reads the same backwards.",
    params=[Param(name="s", type="str")],
    returns="bool",
    edge_cases=["empty string"],
)


def test_classify_returns_kind_and_sends_request():
    caller = FakeCaller({RouterOutput: RouterOutput(kind="python_function")})
    assert classify(caller, "palindrome please").kind == "python_function"
    schema, _system, user = caller.calls[0]
    assert schema is RouterOutput
    assert "palindrome please" in user


def test_extract_requirements_sends_request():
    caller = FakeCaller({Requirements: REQ})
    assert extract_requirements(caller, "palindrome please") == REQ
    assert "palindrome please" in caller.calls[0][2]


def test_generate_code_names_function():
    caller = FakeCaller({CodeOutput: CodeOutput(code="def is_palindrome(s): ...")})
    assert generate_code(caller, REQ).code.startswith("def is_palindrome")
    _schema, system, user = caller.calls[0]
    assert "is_palindrome" in system
    assert "empty string" in user


def test_generate_tests_imports_from_solution():
    caller = FakeCaller({TestsOutput: TestsOutput(tests="def test_x(): pass")})
    generate_tests(caller, REQ, "def is_palindrome(s): ...")
    _schema, system, user = caller.calls[0]
    assert "from solution import is_palindrome" in system
    assert "def is_palindrome(s): ..." in user


def test_model_output_error_propagates():
    caller = FakeCaller({RouterOutput: ModelOutputError("bad json")})
    with pytest.raises(ModelOutputError):
        classify(caller, "anything")


def test_fake_caller_missing_schema_is_model_output_error():
    with pytest.raises(ModelOutputError):
        classify(FakeCaller({}), "anything")


# --- repair agent -------------------------------------------------------------------------

FAKE_KEY = "sk-" + "a1b2" * 6  # obviously fake; shaped like a real key so masking applies


def test_repair_code_sends_masked_pytest_output_and_current_files():
    from codeforge.agents.repair import repair_code

    caller = FakeCaller({CodeOutput: CodeOutput(code="def is_palindrome(s): return True")})
    out = repair_code(caller, REQ, "OLD CODE", "OLD TESTS", f"FAILED test_x leaked {FAKE_KEY}")
    assert out.code.startswith("def is_palindrome")
    schema, system, user = caller.calls[0]
    assert schema is CodeOutput
    assert "OLD CODE" in user and "OLD TESTS" in user
    assert FAKE_KEY not in user and "[SECRET]" in user
    assert "do not change the tests" in system.lower()


def test_repair_code_and_tests_may_change_tests_but_not_weaken_them():
    from codeforge.agents.repair import repair_code_and_tests
    from codeforge.agents.schemas import RepairOutput

    caller = FakeCaller({RepairOutput: RepairOutput(code="C2", tests="T2")})
    out = repair_code_and_tests(caller, REQ, "OLD CODE", "OLD TESTS", f"output {FAKE_KEY}")
    assert (out.code, out.tests) == ("C2", "T2")
    schema, system, user = caller.calls[0]
    assert schema is RepairOutput
    assert FAKE_KEY not in user
    assert "fewer tests" in system.lower()


def test_repair_bad_output_propagates():
    from codeforge.agents.repair import repair_code

    caller = FakeCaller({CodeOutput: ModelOutputError("bad")})
    with pytest.raises(ModelOutputError):
        repair_code(caller, REQ, "c", "t", "out")
