"""Simple stand-ins so the whole graph runs offline. Each is replaced by a real agent later.

- `KeywordRouter`  -> E7 (LLM classification, mixed questions)
- `StubSpecialist` -> E1 to E5 (the real agents)
- `RuleGuardian`   -> stays. `LLMGuardian` (E6) runs these rules first, then a model review
"""

from __future__ import annotations

import re

from penny.contracts import Level, Message, Verdict
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
        (
            "stock price",
            "share price",
            "price of",
            "quote",
            "ticker",
            "trading at",
            "how much is",
            # companies on Penny's watchlist, by the names children use
            "disney",
            "nintendo",
            "roblox",
            "mcdonald",
            "nike",
            "mattel",
            "hasbro",
            "coca-cola",
            "sony",
        ),
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


# Hard caps the Guardian enforces. The writer is asked for fewer, so there is some slack.
MAX_SENTENCES = {Level.STARTER: 5, Level.SAVER: 6, Level.BUILDER: 8}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LIST_OR_HEADING = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#)", re.MULTILINE)


def count_sentences(text: str) -> int:
    return len([part for part in _SENTENCE_END.split(text.strip()) if part.strip()])


class RuleGuardian:
    """The checks that need no model: empty replies, advice or promise wording, and format
    (length for the reader's level, no lists, headings or bold). They are free, instant and
    always give the same answer. `LLMGuardian` runs these first and adds a model review."""

    def review(self, request: AgentRequest, reply: AgentReply) -> Verdict:
        text = reply.text
        if not text.strip():
            return Verdict(approved=False, reasons=["the reply was empty"])
        # A phrase the child used in their own question may be echoed back ("nobody can promise
        # you will get rich"). Whether the reply is really a promise is left to the model review.
        asked, lowered = request.question.lower(), text.lower()
        reasons = [
            f"remove advice or promise wording: '{p}'"
            for p in BANNED_PHRASES
            if p in lowered and p not in asked
        ]
        limit = MAX_SENTENCES[request.kid.level]
        sentences = count_sentences(text)
        if sentences > limit:
            reasons.append(f"too long: {sentences} sentences, the limit is {limit}")
        if _LIST_OR_HEADING.search(text) or "**" in text:
            reasons.append("write plain sentences: no lists, headings or bold")
        return Verdict(approved=not reasons, reasons=reasons)
