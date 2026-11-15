from codeforge.agents.schemas import Requirements, TestsOutput
from codeforge.llm.caller import StructuredCaller


def _system(req: Requirements) -> str:
    return (
        "Write a pytest test module for the function described below.\n"
        f"Import it exactly like this: `from solution import {req.function_name}`.\n"
        "Write plain `def test_...` functions with assert statements. Cover normal cases and "
        "every listed edge case; test the specification, not the implementation's quirks.\n"
        "No network, file or environment access. Return only the module source."
    )


def generate_tests(caller: StructuredCaller, req: Requirements, code: str) -> TestsOutput:
    user = f"Specification (JSON):\n{req.model_dump_json(indent=2)}\n\nImplementation:\n{code}"
    return caller.call(TestsOutput, _system(req), user)
