"""Claude through the Anthropic SDK, behind the provider-neutral `LLMClient` contract.

Translates our neutral `Message` list and `ToolSpec`s into the Messages API format and the
response back into an `LLMResponse`. Two details matter:

- An assistant turn is replayed from `provider_state` (the exact content blocks the API returned),
  never rebuilt, because thinking blocks must go back unchanged.
- Consecutive `tool` messages become ONE user message of `tool_result` blocks, as the API expects.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic

from penny.contracts import Effort, LLMResponse, Message, StopReason, ToolCall, ToolSpec
from penny.llm.errors import LLMError, status_is_retryable

DEFAULT_MAX_TOKENS = 4096  # thinking tokens count toward this, so do not set it too low

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


def _tool_to_wire(tool: ToolSpec) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}


def _assistant_content(message: Message) -> Any:
    if message.provider_state is not None:
        return message.provider_state  # replay exactly what the API returned
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    blocks += [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
        for c in message.tool_calls
    ]
    if not blocks:
        raise ValueError("an assistant message needs text, tool calls or provider_state")
    return blocks


def messages_to_wire(messages: list[Message]) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    def flush() -> None:
        if results:
            wire.append({"role": "user", "content": list(results)})
            results.clear()

    for message in messages:
        if message.role == "tool":
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
            }
            if message.is_error:
                block["is_error"] = True
            results.append(block)
            continue
        flush()
        if message.role == "user":
            wire.append({"role": "user", "content": message.content})
        else:
            wire.append({"role": "assistant", "content": _assistant_content(message)})
    flush()
    return wire


def response_from_wire(response: Any) -> LLMResponse:
    blocks = list(response.content)
    return LLMResponse(
        text="".join(b.text for b in blocks if b.type == "text"),
        tool_calls=[
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in blocks
            if b.type == "tool_use"
        ],
        stop_reason=_STOP_REASONS.get(response.stop_reason, "other"),
        provider_state=blocks,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


class AnthropicClient:
    def __init__(self, client: Any = None, *, default_max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        self._client = client
        self._default_max_tokens = default_max_tokens

    def _api(self) -> Any:
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMError(
                    "ANTHROPIC_API_KEY is not set. Add it to .env, or set LLM_PROVIDER=openai."
                )
            self._client = anthropic.Anthropic()
        return self._client

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int | None = None,
        effort: Effort | None = None,
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self._default_max_tokens,
            "messages": messages_to_wire(messages),
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [_tool_to_wire(t) for t in tools]
        if effort:
            request["output_config"] = {"effort": effort}
        try:
            return response_from_wire(self._api().messages.create(**request))
        except anthropic.APIStatusError as exc:
            raise LLMError(
                f"Anthropic API error {exc.status_code}: {exc.message}",
                retryable=status_is_retryable(exc.status_code),
                status_code=exc.status_code,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach Anthropic: {exc}", retryable=True) from exc
