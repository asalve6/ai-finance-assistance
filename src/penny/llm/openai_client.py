"""OpenAI chat models behind the provider-neutral `LLMClient` contract.

Uses the Chat Completions API. Differences from Anthropic that this adapter hides:

- The system prompt is the first message, not a separate field.
- Tool arguments come back as a JSON *string*. If it does not parse, the call is returned with
  `ToolCall.error` set, so the agent loop can tell the model instead of crashing.
- A tool result has no error flag, so an error is marked with an "Error:" prefix.
- `effort` maps to `reasoning_effort`, which only reasoning models accept (o-series and gpt-5).
  For other models such as gpt-4o it is ignored.
"""

from __future__ import annotations

import json
import os
from typing import Any

import openai

from penny.contracts import Effort, LLMResponse, Message, StopReason, ToolCall, ToolSpec
from penny.llm.errors import LLMError, status_is_retryable

DEFAULT_MAX_TOKENS = 4096
_REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")

_FINISH_REASONS: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


def _tool_to_wire(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def messages_to_wire(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
    for message in messages:
        if message.role == "user":
            wire.append({"role": "user", "content": message.content})
        elif message.role == "tool":
            content = f"Error: {message.content}" if message.is_error else message.content
            wire.append({"role": "tool", "tool_call_id": message.tool_call_id, "content": content})
        else:
            if not message.content and not message.tool_calls:
                raise ValueError("an assistant message needs text or tool calls")
            entry: dict[str, Any] = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.input)},
                    }
                    for call in message.tool_calls
                ]
            wire.append(entry)
    return wire


def _parse_call(raw: Any) -> ToolCall:
    arguments = raw.function.arguments or "{}"
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return ToolCall(
            id=raw.id,
            name=raw.function.name,
            input={},
            error=f"the arguments were not valid JSON: {arguments[:200]}",
        )
    if not isinstance(parsed, dict):
        return ToolCall(
            id=raw.id,
            name=raw.function.name,
            input={},
            error="the arguments must be a JSON object",
        )
    return ToolCall(id=raw.id, name=raw.function.name, input=parsed)


def response_from_wire(response: Any) -> LLMResponse:
    choice = response.choices[0]
    message = choice.message
    stop_reason = _FINISH_REASONS.get(choice.finish_reason, "other")
    if getattr(message, "refusal", None):
        stop_reason = "refusal"
    usage = response.usage
    return LLMResponse(
        text=message.content or "",
        tool_calls=[_parse_call(c) for c in (message.tool_calls or [])],
        stop_reason=stop_reason,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


class OpenAIClient:
    def __init__(self, client: Any = None, *, default_max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        self._client = client
        self._default_max_tokens = default_max_tokens

    def _api(self) -> Any:
        if self._client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise LLMError(
                    "OPENAI_API_KEY is not set. Add it to .env, or set LLM_PROVIDER=anthropic."
                )
            self._client = openai.OpenAI()
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
            "messages": messages_to_wire(system, messages),
            "max_completion_tokens": max_tokens or self._default_max_tokens,
        }
        if tools:
            request["tools"] = [_tool_to_wire(t) for t in tools]
        if effort and model.startswith(_REASONING_MODEL_PREFIXES):
            request["reasoning_effort"] = effort
        try:
            return response_from_wire(self._api().chat.completions.create(**request))
        except openai.APIStatusError as exc:
            raise LLMError(
                f"OpenAI API error {exc.status_code}: {exc.message}",
                retryable=status_is_retryable(exc.status_code),
                status_code=exc.status_code,
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMError(f"Could not reach OpenAI: {exc}", retryable=True) from exc
