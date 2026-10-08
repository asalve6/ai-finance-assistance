from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from penny.contracts import LLMClient, Message, ToolCall, ToolSpec
from penny.llm.anthropic_client import DEFAULT_MAX_TOKENS, AnthropicClient, messages_to_wire
from penny.llm.errors import LLMError

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def tool_block(call_id: str, name: str, **arguments):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def reply(blocks, stop_reason="end_turn", input_tokens=11, output_tokens=7):
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage)


class FakeAnthropic:
    """Stands in for anthropic.Anthropic(): records requests and replays scripted outcomes."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(*outcomes):
    fake = FakeAnthropic(*outcomes)
    return AnthropicClient(fake), fake


LOOKUP = ToolSpec(
    name="lookup",
    description="Look something up. Call only when needed.",
    input_schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    fn=lambda q: q,
)


def test_it_satisfies_the_provider_neutral_contract():
    client: LLMClient = AnthropicClient(FakeAnthropic())
    assert hasattr(client, "complete")


def test_a_plain_request_has_only_what_it_needs():
    client, fake = make(reply([text_block("Hello!")]))
    result = client.complete(model="m", system="Be kind.", messages=[Message.user("Hi")])
    assert fake.requests == [
        {
            "model": "m",
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [{"role": "user", "content": "Hi"}],
            "system": "Be kind.",
        }
    ]
    assert (result.text, result.stop_reason) == ("Hello!", "end_turn")
    assert (result.input_tokens, result.output_tokens) == (11, 7)


def test_max_tokens_effort_and_empty_system_are_passed_correctly():
    client, fake = make(reply([text_block("ok")]))
    client.complete(model="m", system="", messages=[], max_tokens=300, effort="low")
    request = fake.requests[0]
    assert request["max_tokens"] == 300
    assert request["output_config"] == {"effort": "low"}
    assert "system" not in request and "tools" not in request


def test_tools_are_translated_to_the_messages_api_shape():
    client, fake = make(reply([text_block("ok")]))
    client.complete(model="m", system="s", messages=[], tools=[LOOKUP])
    assert fake.requests[0]["tools"] == [
        {
            "name": "lookup",
            "description": "Look something up. Call only when needed.",
            "input_schema": LOOKUP.input_schema,
        }
    ]


def test_tool_calls_and_the_exact_blocks_come_back():
    blocks = [text_block("Checking."), tool_block("t1", "lookup", q="stock")]
    client, _ = make(reply(blocks, stop_reason="tool_use"))
    result = client.complete(model="m", system="s", messages=[Message.user("?")], tools=[LOOKUP])
    assert result.stop_reason == "tool_use"
    assert result.text == "Checking."
    assert result.tool_calls == [ToolCall(id="t1", name="lookup", input={"q": "stock"})]
    assert result.provider_state == blocks and result.provider_state[0] is blocks[0]


def test_multiple_text_blocks_are_joined():
    client, _ = make(reply([text_block("One. "), text_block("Two.")]))
    assert client.complete(model="m", system="", messages=[]).text == "One. Two."


def test_an_assistant_turn_is_replayed_from_provider_state_unchanged():
    blocks = [SimpleNamespace(type="thinking", thinking="", signature="sig"), text_block("hi")]
    assistant = Message(role="assistant", content="hi", provider_state=blocks)
    client, fake = make(reply([text_block("next")]))
    client.complete(model="m", system="", messages=[Message.user("a"), assistant])
    sent = fake.requests[0]["messages"][1]
    assert sent["role"] == "assistant"
    assert sent["content"] is blocks  # the very same blocks, thinking included


def test_an_assistant_turn_without_provider_state_is_rebuilt_from_text_and_calls():
    call = ToolCall(id="t1", name="lookup", input={"q": "x"})
    assistant = Message(role="assistant", content="Checking.", tool_calls=[call])
    assert messages_to_wire([assistant]) == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Checking."},
                {"type": "tool_use", "id": "t1", "name": "lookup", "input": {"q": "x"}},
            ],
        }
    ]
    only_calls = Message(role="assistant", tool_calls=[call])
    assert [b["type"] for b in messages_to_wire([only_calls])[0]["content"]] == ["tool_use"]


def test_an_empty_assistant_turn_is_rejected():
    with pytest.raises(ValueError, match="needs text"):
        messages_to_wire([Message(role="assistant")])


def test_parallel_tool_results_become_one_user_message():
    wire = messages_to_wire(
        [
            Message.user("go"),
            Message(role="assistant", tool_calls=[ToolCall(id="a", name="x", input={})]),
            Message.tool_result("a", "first"),
            Message.tool_result("b", "boom", is_error=True),
            Message.user("thanks"),
        ]
    )
    assert [m["role"] for m in wire] == ["user", "assistant", "user", "user"]
    assert wire[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "a", "content": "first"},
        {"type": "tool_result", "tool_use_id": "b", "content": "boom", "is_error": True},
    ]
    assert wire[3] == {"role": "user", "content": "thanks"}


@pytest.mark.parametrize(
    ("api_reason", "ours"),
    [
        ("end_turn", "end_turn"),
        ("tool_use", "tool_use"),
        ("max_tokens", "max_tokens"),
        ("refusal", "refusal"),
        ("pause_turn", "other"),
        ("stop_sequence", "other"),
    ],
)
def test_stop_reasons_map_to_the_neutral_set(api_reason, ours):
    client, _ = make(reply([text_block("x")], stop_reason=api_reason))
    assert client.complete(model="m", system="", messages=[]).stop_reason == ours


@pytest.mark.parametrize(
    ("error_class", "status", "retryable"),
    [
        (anthropic.RateLimitError, 429, True),
        (anthropic.InternalServerError, 500, True),
        (anthropic.BadRequestError, 400, False),
        (anthropic.AuthenticationError, 401, False),
    ],
)
def test_api_errors_become_llm_errors_with_the_right_retry_flag(error_class, status, retryable):
    error = error_class("nope", response=httpx2.Response(status, request=REQUEST), body=None)
    client, _ = make(error)
    with pytest.raises(LLMError) as raised:
        client.complete(model="m", system="", messages=[])
    assert raised.value.retryable is retryable
    assert raised.value.status_code == status
    assert "nope" in str(raised.value)


def test_network_failures_and_timeouts_are_retryable():
    for error in (
        anthropic.APIConnectionError(request=REQUEST),
        anthropic.APITimeoutError(REQUEST),
    ):
        client, _ = make(error)
        with pytest.raises(LLMError) as raised:
            client.complete(model="m", system="", messages=[])
        assert raised.value.retryable is True and raised.value.status_code is None


def test_a_missing_key_gives_a_helpful_message(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match=r"ANTHROPIC_API_KEY.*LLM_PROVIDER=openai") as raised:
        AnthropicClient().complete(model="m", system="", messages=[])
    assert raised.value.retryable is False


def test_the_real_client_is_created_lazily_from_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    client = AnthropicClient()
    assert client._client is None
    assert isinstance(client._api(), anthropic.Anthropic)
