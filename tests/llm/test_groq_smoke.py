import pytest

from codeforge.agents.router import classify
from codeforge.llm.caller import GroqCaller


@pytest.mark.llm
def test_router_live_palindrome():
    caller = GroqCaller("openai/gpt-oss-120b")
    out = classify(caller, "Write a Python function that checks if a string is a palindrome.")
    assert out.kind == "python_function"
