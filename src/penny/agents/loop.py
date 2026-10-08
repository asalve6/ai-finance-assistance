"""The agent loop: call the model, run the tools it asks for, send the results back, repeat.

    messages -> LLM -+-> plain text ............................ done
                     +-> tool calls -> run each -> tool results -> LLM -> ...

Rules:
- An agent can only use the tools it was given. Anything else comes back to the model as an error.
- A tool that fails, or is called with bad arguments, does not crash the turn. The error goes back
  to the model as the tool's result, so it can correct itself.
- The loop is capped at `max_steps` model calls.
- A cut-off answer (`max_tokens`) or a refusal is an `AgentError`, never half a sentence.
- Every model call and every tool call is recorded as a TraceEvent.
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from penny.contracts import (
    Effort,
    LLMClient,
    Message,
    StopReason,
    ToolCall,
    ToolSpec,
    TraceEvent,
    TraceSink,
)
from penny.observability import NullTraceSink

DEFAULT_MAX_STEPS = 6
_TRACE_TEXT_LIMIT = 500


class AgentError(RuntimeError):
    """The loop could not produce a usable answer (step cap, truncated output, refusal)."""


class ToolRun(BaseModel):
    name: str
    input: dict[str, Any]
    output: str
    is_error: bool = False


class AgentResult(BaseModel):
    text: str
    messages: list[Message]  # the full conversation, including tool calls and results
    steps: int  # how many model calls were made
    tool_runs: list[ToolRun] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: StopReason = "end_turn"


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value, default=str)


def _run_tool(call: ToolCall, tools: dict[str, ToolSpec]) -> tuple[str, bool]:
    """Returns (result text, is_error). Never raises."""
    if call.error:
        return f"The tool was not run: {call.error}", True
    tool = tools.get(call.name)
    if tool is None:
        available = ", ".join(sorted(tools)) or "none"
        return f"Unknown tool '{call.name}'. Available tools: {available}.", True
    try:
        return _to_text(tool.fn(**call.input)), False
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()
        )
        return f"Invalid arguments: {problems}", True
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}", True


def run_agent(
    llm: LLMClient,
    *,
    model: str,
    system: str,
    messages: list[Message],
    tools: list[ToolSpec] | None = None,
    sink: TraceSink | None = None,
    trace_id: str = "",
    agent: str = "agent",
    max_steps: int = DEFAULT_MAX_STEPS,
    max_tokens: int | None = None,
    effort: Effort | None = None,
) -> AgentResult:
    sink = sink or NullTraceSink()
    by_name = {t.name: t for t in tools or []}
    conversation = list(messages)  # never mutate the caller's list
    runs: list[ToolRun] = []
    tokens_in = tokens_out = 0

    for step in range(1, max_steps + 1):
        started = time.perf_counter()
        response = llm.complete(
            model=model,
            system=system,
            messages=conversation,
            tools=tools or None,
            max_tokens=max_tokens,
            effort=effort,
        )
        tokens_in += response.input_tokens
        tokens_out += response.output_tokens
        sink.record(
            TraceEvent(
                trace_id=trace_id,
                agent=agent,
                kind="llm",
                name=model,
                output={
                    "stop_reason": response.stop_reason,
                    "tool_calls": [c.name for c in response.tool_calls],
                    "text": response.text[:_TRACE_TEXT_LIMIT],
                },
                latency_ms=int((time.perf_counter() - started) * 1000),
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        )

        if response.stop_reason == "max_tokens":
            raise AgentError("the model's answer was cut off (max_tokens reached)")
        if response.stop_reason == "refusal":
            raise AgentError("the model declined to answer")
        if not response.tool_calls:
            conversation.append(response.to_message())
            return AgentResult(
                text=response.text,
                messages=conversation,
                steps=step,
                tool_runs=runs,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                stop_reason=response.stop_reason,
            )

        conversation.append(response.to_message())
        for call in response.tool_calls:
            started = time.perf_counter()
            output, is_error = _run_tool(call, by_name)
            runs.append(ToolRun(name=call.name, input=call.input, output=output, is_error=is_error))
            conversation.append(Message.tool_result(call.id, output, is_error=is_error))
            sink.record(
                TraceEvent(
                    trace_id=trace_id,
                    agent=agent,
                    kind="tool",
                    name=call.name,
                    input=call.input,
                    output={"result": output[:_TRACE_TEXT_LIMIT], "is_error": is_error},
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            )

    raise AgentError(f"no final answer after {max_steps} model calls")
