"""AnthropicCaller must not send `temperature`: Claude 5.5 models reject non-default values,
which silently pushed every Run down to the template tier."""

from codeforge.llm.caller import AnthropicCaller


def test_anthropic_caller_sends_no_temperature(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-for-tests")  # obviously fake; no call is made
    caller = AnthropicCaller("claude-haiku-5-5")
    assert caller._llm.temperature is None
