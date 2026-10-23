import json
from types import SimpleNamespace

import httpx2
import openai
import pytest

from penny.contracts import LLMClient, Message, ToolCall, ToolSpec
from penny.llm.errors import LLMError
from penny.llm.openai_client import DEFAULT_MAX_TOKENS, OpenAIClient, messages_to_wire

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def raw_call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def reply(
    content="",
    calls=None,
    finish_reason="stop",
    refusal=None,
    prompt_tokens=11,
    completion_tokens=7,
):
    message = SimpleNamespace(content=content, tool_calls=calls, refusal=refusal)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], usage=usage
    )


class FakeOpenAI:
    """Stands in for openai.OpenAI(): records requests and replays scripted outcomes."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **request):
        self.requests.append(request)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(*outcomes, **options):
    fake = FakeOpenAI(*outcomes)
    return OpenAIClient(fake, **options), fake


LOOKUP = ToolSpec(
    name="lookup",
    description="Look something up.",
    input_schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    fn=lambda q: q,
)


def test_it_satisfies_the_provider_neutral_contract():
    client: LLMClient = OpenAIClient(FakeOpenAI())
    assert hasattr(client, "complete")


def test_a_plain_request_puts_the_system_prompt_first():
    client, fake = make(reply("Hello!"))
    result = client.complete(model="gpt-4o", system="Be kind.", messages=[Message.user("Hi")])
    assert fake.requests == [
        {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "Be kind."},
                {"role": "user", "content": "Hi"},
            ],
            "max_completion_tokens": DEFAULT_MAX_TOKENS,
            "temperature": 0.0,
        }
    ]
    assert (result.text, result.stop_reason) == ("Hello!", "end_turn")
    assert (result.input_tokens, result.output_tokens) == (11, 7)


def test_an_empty_system_prompt_adds_no_system_message():
    client, fake = make(reply("ok"))
    client.complete(model="gpt-4o", system="", messages=[Message.user("Hi")], max_tokens=50)
    assert fake.requests[0]["messages"] == [{"role": "user", "content": "Hi"}]
    assert fake.requests[0]["max_completion_tokens"] == 50


def test_tools_are_translated_to_the_function_shape():
    client, fake = make(reply("ok"))
    client.complete(model="gpt-4o", system="", messages=[], tools=[LOOKUP])
    assert fake.requests[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look something up.",
                "parameters": LOOKUP.input_schema,
            },
        }
    ]


def test_temperature_is_sent_to_normal_models_and_left_out_for_reasoning_models():
    client, fake = make(reply("ok"))
    client.complete(model="gpt-4o", system="", messages=[])
    assert fake.requests[0]["temperature"] == 0.0
    client, fake = make(reply("ok"))
    client.complete(model="gpt-5", system="", messages=[])
    assert "temperature" not in fake.requests[0]
    client, fake = make(reply("ok"), temperature=None)
    client.complete(model="gpt-4o", system="", messages=[])
    assert "temperature" not in fake.requests[0]


@pytest.mark.parametrize(
    ("model", "sent"),
    [("gpt-5", True), ("o3-mini", True), ("gpt-4o", False), ("gpt-4o-mini", False)],
)
def test_effort_is_sent_only_to_reasoning_models(model, sent):
    client, fake = make(reply("ok"))
    client.complete(model=model, system="", messages=[], effort="low")
    assert ("reasoning_effort" in fake.requests[0]) is sent
    if sent:
        assert fake.requests[0]["reasoning_effort"] == "low"


def test_tool_calls_are_parsed_from_the_json_string():
    calls = [raw_call("c1", "lookup", '{"q": "stock"}')]
    client, _ = make(reply(None, calls, finish_reason="tool_calls"))
    result = client.complete(model="gpt-4o", system="", messages=[], tools=[LOOKUP])
    assert result.stop_reason == "tool_use" and result.text == ""
    assert result.tool_calls == [ToolCall(id="c1", name="lookup", input={"q": "stock"})]
    assert result.provider_state is None


def test_invalid_tool_arguments_are_flagged_not_fatal():
    calls = [raw_call("c1", "lookup", "{not json"), raw_call("c2", "lookup", "[1, 2]")]
    client, _ = make(reply(None, calls, finish_reason="tool_calls"))
    result = client.complete(model="gpt-4o", system="", messages=[])
    assert [c.input for c in result.tool_calls] == [{}, {}]
    assert "not valid JSON: {not json" in result.tool_calls[0].error
    assert "must be a JSON object" in result.tool_calls[1].error


def test_empty_arguments_mean_no_arguments():
    client, _ = make(reply(None, [raw_call("c1", "lookup", "")], finish_reason="tool_calls"))
    call = client.complete(model="gpt-4o", system="", messages=[]).tool_calls[0]
    assert call.input == {} and call.error is None


def test_an_assistant_turn_with_calls_and_tool_results_round_trip():
    call = ToolCall(id="c1", name="lookup", input={"q": "x"})
    wire = messages_to_wire(
        "",
        [
            Message.user("go"),
            Message(role="assistant", content="Checking.", tool_calls=[call]),
            Message.tool_result("c1", '{"found": true}'),
            Message.tool_result("c2", "boom", is_error=True),
        ],
    )
    assert wire[1] == {
        "role": "assistant",
        "content": "Checking.",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "lookup", "arguments": json.dumps({"q": "x"})},
            }
        ],
    }
    assert wire[2] == {"role": "tool", "tool_call_id": "c1", "content": '{"found": true}'}
    assert wire[3]["content"] == "Error: boom"


def test_an_assistant_turn_with_only_tool_calls_has_null_content():
    call = ToolCall(id="c1", name="lookup", input={})
    entry = messages_to_wire("", [Message(role="assistant", tool_calls=[call])])[0]
    assert entry["content"] is None


def test_an_empty_assistant_turn_is_rejected():
    with pytest.raises(ValueError, match="needs text"):
        messages_to_wire("", [Message(role="assistant")])


@pytest.mark.parametrize(
    ("finish_reason", "ours"),
    [
        ("stop", "end_turn"),
        ("tool_calls", "tool_use"),
        ("length", "max_tokens"),
        ("content_filter", "refusal"),
        ("something_new", "other"),
    ],
)
def test_finish_reasons_map_to_the_neutral_set(finish_reason, ours):
    client, _ = make(reply("x", finish_reason=finish_reason))
    assert client.complete(model="gpt-4o", system="", messages=[]).stop_reason == ours


def test_a_model_refusal_is_reported_as_a_refusal():
    client, _ = make(reply(None, refusal="I can't help with that."))
    assert client.complete(model="gpt-4o", system="", messages=[]).stop_reason == "refusal"


def test_missing_usage_counts_as_zero():
    response = reply("x")
    response.usage = None
    client, _ = make(response)
    result = client.complete(model="gpt-4o", system="", messages=[])
    assert (result.input_tokens, result.output_tokens) == (0, 0)


@pytest.mark.parametrize(
    ("error_class", "status", "retryable"),
    [
        (openai.RateLimitError, 429, True),
        (openai.InternalServerError, 500, True),
        (openai.BadRequestError, 400, False),
        (openai.AuthenticationError, 401, False),
    ],
)
def test_api_errors_become_llm_errors_with_the_right_retry_flag(error_class, status, retryable):
    error = error_class("nope", response=httpx2.Response(status, request=REQUEST), body=None)
    client, _ = make(error)
    with pytest.raises(LLMError) as raised:
        client.complete(model="gpt-4o", system="", messages=[])
    assert raised.value.retryable is retryable and raised.value.status_code == status
    assert "nope" in str(raised.value)


def test_network_failures_and_timeouts_are_retryable():
    for error in (openai.APIConnectionError(request=REQUEST), openai.APITimeoutError(REQUEST)):
        client, _ = make(error)
        with pytest.raises(LLMError) as raised:
            client.complete(model="gpt-4o", system="", messages=[])
        assert raised.value.retryable is True and raised.value.status_code is None


def test_a_missing_key_gives_a_helpful_message(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match=r"OPENAI_API_KEY.*LLM_PROVIDER=anthropic"):
        OpenAIClient().complete(model="gpt-4o", system="", messages=[])


def test_the_real_client_is_created_lazily_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    client = OpenAIClient()
    assert client._client is None
    assert isinstance(client._api(), openai.OpenAI)
