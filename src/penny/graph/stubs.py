"""Simple stand-ins so the whole graph runs offline. Each is replaced by a real agent later.

- `KeywordRouter`  -> E7 (LLM classification, mixed questions)
- `StubSpecialist` -> E1 to E5 (the real agents)
- `RuleGuardian`   -> E6 (LLM review on top of these rules)
"""

from __future__ import annotations

from penny.contracts import Message, Verdict
from penny.graph.types import (
    SPECIALISTS,
    AgentReply,
    AgentRequest,
    KidContext,
    RouteDecision,
    Specialist,
)
from penny.kb.checks import BANNED_PHRASES

SAFE_FALLBACK = (
    "I'm not sure how to explain that well yet. Could you ask it a different way? "
    "You can also talk it over with a grown-up."
)

# Checked in this order, so "tax" wins over the generic words in "why is my paycheck smaller".
_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tax", ("tax", "paycheck", "401k", "401(k)", "roth", "withhold", " ira")),
    ("portfolio", ("portfolio", "diversif", "holdings", "asset allocation", "my stocks")),
    (
        "market",
        ("stock price", "share price", "price of", "quote", "ticker", "trading at", "how much is"),
    ),
    (
        "coach",
        (
            "goal",
            "save up",
            "saving for",
            "lemonade",
            "piggy",
            "game",
            "coins",
            "per week",
            "streak",
        ),
    ),
)


class KeywordRouter:
    """First matching keyword group wins; anything else goes to finance_qa."""

    def route(self, question: str, history: list[Message], kid: KidContext) -> RouteDecision:
        text = f" {question.lower()} "
        for agent, keywords in _ROUTES:
            for keyword in keywords:
                if keyword in text:
                    return RouteDecision(agent=agent, reason=f"matched '{keyword.strip()}'")
        return RouteDecision(agent="finance_qa", reason="default")


class StubSpecialist:
    def __init__(self, name: str) -> None:
        self.name = name

    def respond(self, request: AgentRequest) -> AgentReply:
        note = f" (revising: {'; '.join(request.feedback)})" if request.feedback else ""
        return AgentReply(text=f"[{self.name}] stub answer for: {request.question}{note}")


def default_agents() -> dict[str, Specialist]:
    return {name: StubSpecialist(name) for name in SPECIALISTS}


class RuleGuardian:
    """Rejects empty replies and advice or promise wording. The LLM Guardian (E6) adds tone,
    reading level and fact checks on top."""

    def review(self, request: AgentRequest, reply: AgentReply) -> Verdict:
        if not reply.text.strip():
            return Verdict(approved=False, reasons=["the reply was empty"])
        lowered = reply.text.lower()
        found = [p for p in BANNED_PHRASES if p in lowered]
        if found:
            return Verdict(
                approved=False,
                reasons=[f"remove advice or promise wording: '{p}'" for p in found],
            )
        return Verdict(approved=True)
