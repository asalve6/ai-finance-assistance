import json

import pytest
from pydantic import BaseModel, Field

from penny.agents.loop import AgentError, run_agent
from penny.agents.tools import make_tool
from penny.contracts import LLMResponse, Message, ToolCall
from penny.llm.errors import LLMError
from penny.llm.fake import FakeLLM
from penny.observability import InMemoryTraceSink


class AddArgs(BaseModel):
    a: int
    b: int = Field(default=0, ge=0)


calls_seen: list[dict] = []


def add(a: int, b: int) -> dict:
    calls_seen.append({"a": a, "b": b})
    return {"sum": a + b}


def boom(a: int, b: int) -> dict:
    raise RuntimeError("database is down")


ADD = make_tool("add", "Add two whole numbers.", AddArgs, add)
BOOM = make_tool("boom", "Always fails.", AddArgs, boom)


@pytest.fixture(autouse=True)
def _reset():
    calls_seen.clear()


def wants(*calls: ToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=list(calls),
        stop_reason="tool_use",
        provider_state=["opaque"],
        input_tokens=10,
        output_tokens=5,
    )


def says(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=20, output_tokens=8)


def call(call_id="c1", name="add", error=None, **arguments) -> ToolCall:
    return ToolCall(id=call_id, name=name, input=arguments, error=error)


def run(llm, **kwargs):
    kwargs.setdefault("tools", [ADD])
    return run_agent(llm, model="m", system="s", messages=[Message.user("hi")], **kwargs)


# ------------------------------------------------------------------ the basic shapes


def test_a_plain_answer_needs_one_model_call():
    llm = FakeLLM([says("Hello!")])
    result = run(llm)
    assert (result.text, result.steps, result.tool_runs) == ("Hello!", 1, [])
    assert [m.role for m in result.messages] == ["user", "assistant"]
    assert (result.input_tokens, result.output_tokens) == (20, 8)


def test_one_tool_round_trip():
    llm = FakeLLM([wants(call(a=17, b=25)), says("It is 42.")])
    result = run(llm)

    assert result.text == "It is 42." and result.steps == 2
    assert calls_seen == [{"a": 17, "b": 25}]
    assert result.tool_runs[0].output == '{"sum": 42}' and not result.tool_runs[0].is_error
    # the second model call saw the assistant turn and the tool result
    second = llm.calls[1]["messages"]
    assert [m.role for m in second] == ["user", "assistant", "tool"]
    assert second[1].provider_state == ["opaque"]  # replayed unchanged for the provider
    assert (second[2].tool_call_id, second[2].content, second[2].is_error) == (
        "c1",
        '{"sum": 42}',
        False,
    )
    assert (result.input_tokens, result.output_tokens) == (30, 13)


def test_parallel_tool_calls_all_run_and_all_results_go_back_in_order():
    llm = FakeLLM([wants(call("c1", a=1, b=2), call("c2", a=10, b=20)), says("3 and 30.")])
    result = run(llm)
    tool_messages = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert [(m.tool_call_id, json.loads(m.content)["sum"]) for m in tool_messages] == [
        ("c1", 3),
        ("c2", 30),
    ]
    assert len(result.tool_runs) == 2


def test_the_model_can_use_tools_over_several_steps():
    llm = FakeLLM([wants(call("c1", a=1, b=1)), wants(call("c2", a=2, b=2)), says("done")])
    result = run(llm)
    assert result.steps == 3 and [r.input for r in result.tool_runs] == [
        {"a": 1, "b": 1},
        {"a": 2, "b": 2},
    ]


def test_an_agent_without_tools_still_works_and_sends_no_tool_list():
    llm = FakeLLM([says("Hello!")])
    assert run(llm, tools=None).text == "Hello!"
    assert llm.calls[0]["tools"] is None


def test_settings_are_passed_to_the_model_and_the_callers_list_is_untouched():
    llm = FakeLLM([wants(call(a=1, b=1)), says("ok")])
    original = [Message.user("hi")]
    run_agent(
        llm, model="m", system="sys", messages=original, tools=[ADD], max_tokens=300, effort="low"
    )
    assert len(original) == 1
    first = llm.calls[0]
    assert (first["model"], first["system"], first["max_tokens"], first["effort"]) == (
        "m",
        "sys",
        300,
        "low",
    )


# ------------------------------------------------------------------ errors go back to the model


def test_a_failing_tool_is_reported_to_the_model_which_can_recover():
    llm = FakeLLM([wants(call(name="boom", a=1, b=1)), says("Sorry, I could not check that.")])
    result = run(llm, tools=[ADD, BOOM])
    assert result.text.startswith("Sorry")
    sent = llm.calls[1]["messages"][-1]
    assert sent.is_error is True and sent.content == "RuntimeError: database is down"
    assert result.tool_runs[0].is_error is True


def test_an_unknown_tool_is_refused_and_the_real_ones_are_listed():
    llm = FakeLLM([wants(call(name="delete_everything")), says("ok")])
    result = run(llm, tools=[ADD, BOOM])
    assert result.tool_runs[0].output == (
        "Unknown tool 'delete_everything'. Available tools: add, boom."
    )
    assert result.tool_runs[0].is_error is True and calls_seen == []


def test_an_agent_cannot_use_a_tool_it_was_not_given():
    llm = FakeLLM([wants(call(name="add", a=1, b=1)), says("ok")])
    result = run(llm, tools=[BOOM])  # `add` exists in the app, but not for this agent
    assert "Unknown tool 'add'" in result.tool_runs[0].output and calls_seen == []


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"a": "seventeen", "b": 1}, "a: "),
        ({"a": 1}, None),  # b has a default, so this is valid
        ({"b": 1}, "a: Field required"),
        ({"a": 1, "b": -5}, "b: "),
    ],
)
def test_arguments_are_validated_before_the_tool_runs(arguments, fragment):
    llm = FakeLLM([wants(call(**arguments)), says("ok")])
    run_output = run(llm).tool_runs[0]
    if fragment is None:
        assert not run_output.is_error and calls_seen == [{"a": 1, "b": 0}]
    else:
        assert run_output.is_error and run_output.output.startswith("Invalid arguments: ")
        assert fragment in run_output.output and calls_seen == []


def test_unparseable_arguments_from_the_provider_are_reported_without_running_the_tool():
    llm = FakeLLM([wants(call(error="the arguments were not valid JSON: {oops")), says("ok")])
    output = run(llm).tool_runs[0]
    assert output.is_error and "not valid JSON" in output.output and calls_seen == []


def test_one_bad_call_does_not_stop_the_good_one_beside_it():
    llm = FakeLLM([wants(call("c1", name="nope"), call("c2", a=2, b=3)), says("ok")])
    result = run(llm)
    assert [r.is_error for r in result.tool_runs] == [True, False]
    assert calls_seen == [{"a": 2, "b": 3}]


# ------------------------------------------------------------------ results are serialised


class Quote(BaseModel):
    symbol: str
    price_cents: int


@pytest.mark.parametrize(
    ("returned", "expected"),
    [
        ("plain text", "plain text"),
        ({"k": [1, 2]}, '{"k": [1, 2]}'),
        (Quote(symbol="NTDOY", price_cents=1500), '{"symbol":"NTDOY","price_cents":1500}'),
        (42, "42"),
        (None, "null"),
    ],
)
def test_tool_results_become_text(returned, expected):
    tool = make_tool("t", "returns something", AddArgs, lambda a, b: returned)
    llm = FakeLLM([wants(call(name="t", a=1, b=1)), says("ok")])
    assert run(llm, tools=[tool]).tool_runs[0].output == expected


# ------------------------------------------------------------------ stopping conditions


def test_the_loop_stops_at_the_step_cap():
    llm = FakeLLM([wants(call(a=1, b=1))] * 3)
    with pytest.raises(AgentError, match="no final answer after 3 model calls"):
        run(llm, max_steps=3)
    assert len(llm.calls) == 3


def test_a_cut_off_answer_is_an_error_not_half_a_sentence():
    llm = FakeLLM([LLMResponse(text="A stock is a sm", stop_reason="max_tokens")])
    with pytest.raises(AgentError, match="cut off"):
        run(llm)


def test_a_refusal_is_an_error():
    llm = FakeLLM([LLMResponse(stop_reason="refusal")])
    with pytest.raises(AgentError, match="declined"):
        run(llm)


def test_provider_failures_pass_straight_through():
    class Down:
        def complete(self, **kwargs):
            raise LLMError("rate limited", retryable=True, status_code=429)

    with pytest.raises(LLMError) as raised:
        run(Down())
    assert raised.value.retryable is True


# ------------------------------------------------------------------ tracing


def test_every_model_call_and_tool_call_is_traced_in_order():
    sink = InMemoryTraceSink()
    llm = FakeLLM([wants(call(a=17, b=25), text="Let me add."), says("It is 42.")])
    run(llm, sink=sink, trace_id="t1", agent="coach")

    events = sink.for_trace("t1")
    assert [(e.agent, e.kind, e.name) for e in events] == [
        ("coach", "llm", "m"),
        ("coach", "tool", "add"),
        ("coach", "llm", "m"),
    ]
    assert events[0].output == {
        "stop_reason": "tool_use",
        "tool_calls": ["add"],
        "text": "Let me add.",
    }
    assert (events[0].input_tokens, events[0].output_tokens) == (10, 5)
    assert events[1].input == {"a": 17, "b": 25}
    assert events[1].output == {"result": '{"sum": 42}', "is_error": False}
    assert events[2].output["text"] == "It is 42."


def test_long_text_is_trimmed_in_the_trace_but_not_in_the_result():
    sink = InMemoryTraceSink()
    long_answer = "x" * 2000
    result = run(FakeLLM([says(long_answer)]), sink=sink, trace_id="t")
    assert len(result.text) == 2000
    assert len(sink.events[0].output["text"]) == 500


# ------------------------------------------------------------------ make_tool


def test_make_tool_exposes_a_json_schema_the_providers_can_use():
    schema = ADD.input_schema
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"a", "b"}
    assert schema["required"] == ["a"]
    assert (ADD.name, ADD.description) == ("add", "Add two whole numbers.")
