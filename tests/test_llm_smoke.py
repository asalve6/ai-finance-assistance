import pytest

from penny.contracts import LLMResponse, ToolCall
from penny.llm import smoke
from penny.llm.errors import LLMError
from penny.llm.factory import LLMSetup
from penny.llm.fake import FakeLLM


def asks_for_the_tool(arguments=None, error=None):
    call = ToolCall(id="c1", name="add", input=arguments or {"a": 17, "b": 25}, error=error)
    return LLMResponse(tool_calls=[call], stop_reason="tool_use", input_tokens=10, output_tokens=5)


def test_a_working_provider_passes():
    llm = FakeLLM([asks_for_the_tool(), LLMResponse(text="17 plus 25 is 42.", input_tokens=20)])
    outcome = smoke.run_smoke(llm, "m")
    assert outcome["ok"] is True
    assert outcome["tool_input"] == {"a": 17, "b": 25}
    assert outcome["tokens"] == 35
    # the second call carried the assistant turn and the tool result back to the model
    roles = [m.role for m in llm.calls[1]["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert llm.calls[1]["messages"][2].content == '{"sum": 42}'


def test_the_model_ignoring_the_tool_fails_at_the_first_step():
    outcome = smoke.run_smoke(FakeLLM([LLMResponse(text="It is 42.")]), "m")
    assert (outcome["ok"], outcome["step"]) == (False, "tool request")


def test_unparseable_tool_arguments_are_reported():
    outcome = smoke.run_smoke(FakeLLM([asks_for_the_tool(error="bad json")]), "m")
    assert (outcome["ok"], outcome["step"], outcome["detail"]) == (
        False,
        "tool arguments",
        "bad json",
    )


def test_a_wrong_final_answer_fails():
    llm = FakeLLM([asks_for_the_tool({"a": 1, "b": 1}), LLMResponse(text="It is 2.")])
    assert smoke.run_smoke(llm, "m")["ok"] is False


def patch_setup(monkeypatch, llm):
    monkeypatch.setattr(
        smoke, "get_llm", lambda provider=None: LLMSetup(llm, "fake", "fast-m", "main-m")
    )


def test_the_command_reports_pass_and_uses_the_chosen_tier(monkeypatch, capsys):
    llm = FakeLLM([asks_for_the_tool(), LLMResponse(text="42")])
    patch_setup(monkeypatch, llm)
    assert smoke.main(["--tier", "main"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert llm.calls[0]["model"] == "main-m"


def test_the_command_reports_failure_with_exit_code_1(monkeypatch, capsys):
    patch_setup(monkeypatch, FakeLLM([LLMResponse(text="no tool")]))
    assert smoke.main([]) == 1
    assert "FAIL at tool request" in capsys.readouterr().out


def test_configuration_errors_are_one_clean_line(monkeypatch, capsys):
    def broken(provider=None):
        raise LLMError("OPENAI_API_KEY is not set.")

    monkeypatch.setattr(smoke, "get_llm", broken)
    assert smoke.main([]) == 2
    assert capsys.readouterr().out.strip() == "Error: OPENAI_API_KEY is not set."


@pytest.mark.parametrize("tier", ["fast", "main"])
def test_the_default_tier_is_fast_and_both_are_accepted(monkeypatch, tier):
    llm = FakeLLM([asks_for_the_tool(), LLMResponse(text="42")])
    patch_setup(monkeypatch, llm)
    smoke.main(["--tier", tier])
    assert llm.calls[0]["model"] == f"{tier}-m"
