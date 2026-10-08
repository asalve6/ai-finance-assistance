"""Shared contracts. Every lane codes against these, so lanes can be built in parallel.

Rules of the road:
- Engines are pure: no DB, no LLM, no clock. Randomness comes from a seed.
- Agents never share chat history. They exchange a `Handoff` and read facts from the DB.
- Every LLM or tool call is reported to a `TraceSink`.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class Level(StrEnum):
    STARTER = "starter"
    SAVER = "saver"
    BUILDER = "builder"


class GameType(StrEnum):
    PIGGY = "piggy"
    LEMONADE = "lemonade"


class AgentName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    ASSESSOR = "assessor"
    COACH = "coach"
    GUARDIAN = "guardian"
    REPORTER = "reporter"


# ---------------------------------------------------------------- engines (pure code)


class GameState(BaseModel):
    """Everything an engine needs to resume a run. Stored as JSON in game_runs.state_json."""

    game_type: GameType
    seed: int
    day: int = 1
    total_days: int = 3
    data: dict[str, Any] = Field(default_factory=dict)
    finished: bool = False


class GameFacts(BaseModel):
    """What happened on one day. The Coach explains these; it never invents or changes them."""

    day: int
    decision: dict[str, Any]
    outcome: dict[str, Any]
    profit_cents: int
    coins_earned: int
    xp_earned: int
    finished: bool


class GameEngine(Protocol):
    game_type: GameType

    def start(self, level: Level, seed: int) -> GameState: ...

    def submit(self, state: GameState, decision: dict[str, Any]) -> tuple[GameState, GameFacts]: ...


# ---------------------------------------------------------------- agents


class Handoff(BaseModel):
    """Structured message between agents. Small on purpose: context isolation."""

    trace_id: str
    kid_id: int
    intent: str
    context_summary: str = ""


class Verdict(BaseModel):
    """Guardian output."""

    approved: bool
    reasons: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    """A tool an agent may call. `fn` is excluded from serialisation."""

    name: str
    description: str  # what it does, when to call it, when NOT to
    input_schema: dict[str, Any]
    fn: Callable[..., Any] = Field(exclude=True)


# ---------------------------------------------------------------- LLM boundary
# A provider-neutral conversation format. Each adapter (Anthropic, OpenAI, ...) translates it to
# its own wire format and back, so agents, the graph and tests never see provider details.

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]
Effort = Literal["low", "medium", "high"]


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]
    # Set by an adapter when the model's arguments could not be parsed. The agent loop reports it
    # back to the model as a tool error instead of running the tool.
    error: str | None = None


class Message(BaseModel):
    """One turn of a conversation. A `tool` message carries the result of exactly one ToolCall."""

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)  # assistant only
    tool_call_id: str | None = None  # tool only
    is_error: bool = False  # tool only
    # Provider-private data (for example thinking blocks) that must go back unchanged on the next
    # call. Opaque to everything except the adapter that produced it. Never serialised.
    provider_state: Any = Field(default=None, exclude=True)

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", content=text)

    @classmethod
    def tool_result(cls, call_id: str, content: str, *, is_error: bool = False) -> Message:
        return cls(role="tool", content=content, tool_call_id=call_id, is_error=is_error)


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = "end_turn"
    provider_state: Any = Field(default=None, exclude=True)
    input_tokens: int = 0
    output_tokens: int = 0

    def to_message(self) -> Message:
        """The assistant turn to append to the conversation before sending tool results."""
        return Message(
            role="assistant",
            content=self.text,
            tool_calls=self.tool_calls,
            provider_state=self.provider_state,
        )


class LLMClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int | None = None,
        effort: Effort | None = None,
    ) -> LLMResponse: ...


# ---------------------------------------------------------------- observability


class TraceEvent(BaseModel):
    trace_id: str
    agent: AgentName | str
    kind: str  # "llm" | "tool" | "route" | "verdict"
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class TraceSink(Protocol):
    def record(self, event: TraceEvent) -> None: ...
