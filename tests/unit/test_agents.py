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
