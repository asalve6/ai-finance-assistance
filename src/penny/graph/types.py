"""The small interfaces the graph is built on.

Every real decision (which agent answers, what the answer is, whether it is safe) sits behind one
of these, so each can be replaced independently: the router (E7), each specialist (E1-E5) and the
Guardian (E6). The graph itself only wires them together.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from penny.contracts import Level, Message, Verdict
from penny.kb.retriever import Citation

SPECIALISTS = ("finance_qa", "coach", "market", "portfolio", "tax")
RESERVED_NODE_NAMES = frozenset({"intake", "router", "guardian", "fallback", "respond"})


class KidContext(BaseModel):
    kid_id: int = 0
    nickname: str = "friend"
    level: Level = Level.STARTER
    # The child's practice portfolio: ticker -> number of shares. Practice money only.
    practice_holdings: dict[str, int] = Field(default_factory=dict)


class AgentRequest(BaseModel):
    trace_id: str
    kid: KidContext
    question: str
    history: list[Message] = Field(default_factory=list)  # earlier turns of this session only
    feedback: list[str] = Field(default_factory=list)  # why the Guardian rejected the last draft
    also_ask: str = ""  # a part of the question another specialist answers next, so skip it


class AgentReply(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    # The passages or facts the reply was written from. The Guardian checks the reply against it.
    evidence: str = ""


class RouteDecision(BaseModel):
    agent: str
    reason: str = ""
    # For a mixed question: the part another specialist should answer, as its own question.
    also_ask: str = ""


class TurnResult(BaseModel):
    reply: str
    route: str
    route_reason: str
    approved: bool  # False when the safe fallback was used
    rewrites: int  # how many drafts the Guardian rejected this turn
    fallback_used: bool
    trace_id: str
    citations: list[Citation] = Field(default_factory=list)
    last_issues: list[str] = Field(default_factory=list)
    also_ask: str = ""  # the other part of a mixed question, offered to the child as a button


class Router(Protocol):
    def route(
        self, question: str, history: list[Message], kid: KidContext, trace_id: str = ""
    ) -> RouteDecision: ...


class Specialist(Protocol):
    def respond(self, request: AgentRequest) -> AgentReply: ...


class Guardian(Protocol):
    def review(self, request: AgentRequest, reply: AgentReply) -> Verdict: ...
