import pytest

from penny.contracts import GameState, GameType, LLMResponse, ToolCall
from penny.llm.fake import FakeLLM


def test_game_state_round_trips_through_json():
    state = GameState(game_type=GameType.LEMONADE, seed=7, data={"cash_cents": 1200})
    assert GameState.model_validate_json(state.model_dump_json()) == state


def test_fake_llm_replays_script_and_records_calls():
    call = ToolCall(id="1", name="x", input={})
    llm = FakeLLM([LLMResponse(text="hi"), LLMResponse(tool_calls=[call])])
    first = llm.complete(model="m", system="s", messages=[])
    second = llm.complete(model="m", system="s", messages=[])
    assert first.text == "hi"
    assert second.tool_calls[0].name == "x"
    assert len(llm.calls) == 2


def test_fake_llm_fails_loudly_when_script_runs_out():
    llm = FakeLLM([])
    with pytest.raises(AssertionError):
        llm.complete(model="m", system="s", messages=[])
