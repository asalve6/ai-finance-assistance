"""Shared contracts. Every lane codes against these, so lanes can be built in parallel.

Rules of the road:
- Engines are pure: no DB, no LLM, no clock. Randomness comes from a seed.
- Agents never share chat history. They exchange a `Handoff` and read facts from the DB.
- Every LLM or tool call is reported to a `TraceSink`.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Protocol

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


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
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
