import pytest

from penny.contracts import GameState, GameType, LLMResponse, Message, ToolCall
from penny.llm.fake import FakeLLM


def test_game_state_round_trips_through_json():
    state = GameState(game_type=GameType.LEMONADE, seed=7, data={"cash_cents": 1200})
    assert GameState.model_validate_json(state.model_dump_json()) == state


def test_fake_llm_replays_script_and_records_calls():
    call = ToolCall(id="1", name="x", input={})
    llm = FakeLLM([LLMResponse(text="hi"), LLMResponse(tool_calls=[call], stop_reason="tool_use")])
    first = llm.complete(model="m", system="s", messages=[Message.user("hello")])
    second = llm.complete(model="m", system="s", messages=[], max_tokens=50, effort="low")
    assert first.text == "hi"
    assert second.tool_calls[0].name == "x"
    assert len(llm.calls) == 2
    assert llm.calls[0]["messages"][0].content == "hello"
    assert (llm.calls[1]["max_tokens"], llm.calls[1]["effort"]) == (50, "low")


def test_fake_llm_fails_loudly_when_script_runs_out():
    llm = FakeLLM([])
    with pytest.raises(AssertionError):
        llm.complete(model="m", system="s", messages=[])


def test_response_defaults_to_a_normal_finish():
    assert LLMResponse(text="ok").stop_reason == "end_turn"


def test_to_message_builds_the_assistant_turn_with_calls_and_provider_state():
    call = ToolCall(id="t1", name="lookup", input={"q": "x"})
    state = [{"type": "thinking"}]
    response = LLMResponse(
        text="checking", tool_calls=[call], stop_reason="tool_use", provider_state=state
    )
    message = response.to_message()
    assert message.role == "assistant"
    assert message.content == "checking"
    assert message.tool_calls == [call]
    assert message.provider_state is state


def test_tool_result_message_links_back_to_the_call_and_can_flag_errors():
    ok = Message.tool_result("t1", '{"sold": 20}')
    bad = Message.tool_result("t2", "boom", is_error=True)
    assert (ok.role, ok.tool_call_id, ok.is_error) == ("tool", "t1", False)
    assert bad.is_error is True


def test_provider_state_is_never_serialised():
    message = Message(role="assistant", content="hi", provider_state={"secret": "blocks"})
    dumped = message.model_dump()
    assert "provider_state" not in dumped
    assert "secret" not in message.model_dump_json()
    assert Message.model_validate_json(message.model_dump_json()).provider_state is None
