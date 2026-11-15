from types import SimpleNamespace

from codeforge.agents.testgen import _system


def test_system_prompt_requires_verified_expected_results():
    prompt = _system(SimpleNamespace(function_name="is_palindrome"))

    assert "Every expected result must be mathematically verified." in prompt
    assert "compare its normalized form with its reverse" in prompt
    assert "Never create contradictory or incorrect expected values." in prompt
