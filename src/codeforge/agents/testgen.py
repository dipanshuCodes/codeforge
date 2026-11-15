from codeforge.agents.schemas import Requirements, TestsOutput
from codeforge.llm.caller import StructuredCaller


def _system(req: Requirements) -> str:
    prompt = (
        "Write a pytest test module for the function described below.\n"
        f"Import it exactly like this: `from solution import {req.function_name}`.\n"
        "Write plain `def test_...` functions with assert statements. Cover normal cases and "
        "every listed edge case; test the specification, not the implementation's quirks.\n"
        "No network, file or environment access. Return only the module source.\n"
        "Every expected result must be mathematically verified.\n"
        "Before asserting a string is not a palindrome, compare its normalized form with its reverse.\n"
        "CRITICAL TEST-CORRECTNESS RULES:\n"
        "1. Calculate the expected result independently for every test input before writing an assertion.\n"
        "2. Never guess an expected result or copy an assumption from a comment.\n"
        "3. Check that every test input actually produces the expected result.\n"
        "4. Do not create contradictory assertions or invalid test fixtures.\n"
        "5. Do not use the implementation itself to calculate expected results.\n"
    )

    if req.function_name == "is_palindrome":
        prompt += (
            "PALINDROME-SPECIFIC RULES:\n"
            "Normalize each input exactly as the specification requires, then compare the "
            "normalized string with its reverse.\n"
            "A string is a palindrome if and only if those two strings are equal.\n"
            "For example, 'ab!ba' IS a palindrome when punctuation is retained.\n"
            "The string 'a' * 5000 + 'b' + 'a' * 5000 IS also a palindrome.\n"
            "Use 'a' * 5000 + 'b' + 'a' * 4999 as a verified non-palindrome example.\n"
            "Never label a palindrome as a non-palindrome.\n"
            "Never create contradictory or incorrect expected values.\n"
        )

    return prompt


def generate_tests(caller: StructuredCaller, req: Requirements, code: str) -> TestsOutput:
    user = f"Specification (JSON):\n{req.model_dump_json(indent=2)}\n\nImplementation:\n{code}"
    return caller.call(TestsOutput, _system(req), user)
