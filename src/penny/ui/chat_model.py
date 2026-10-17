"""Turn a graph result and its trace into what the Chat tab shows. Pure, so it is easy to test."""

from __future__ import annotations

from pydantic import BaseModel, Field

from penny.contracts import TraceEvent
from penny.graph.types import TurnResult
from penny.kb.retriever import Citation
from penny.ui.text import md

AGENT_LABELS = {
    "finance_qa": "Finance Q&A",
    "tax": "Tax Education",
    "coach": "Goal and Game Coach",
    "market": "Market Analysis",
    "portfolio": "Portfolio Analysis",
    "guardian": "Guardian",
    "router": "Router",
    "graph": "Penny",
}

GREETING = "Hi! I'm Penny. Ask me a money question, or pick one below."

SUGGESTIONS = (
    "What is a stock?",
    "Why is my first paycheck smaller?",
    "I want a $60 game in 8 weeks. How much per week?",
    "How do I cook pasta?",
)


class TraceRow(BaseModel):
    who: str
    what: str
    ms: str = ""


class ChatTurn(BaseModel):
    question: str
    reply: str
    caption: str
    citations: list[Citation] = Field(default_factory=list)
    trace: list[TraceRow] = Field(default_factory=list)


def label(agent: str) -> str:
    return AGENT_LABELS.get(agent, agent)


def describe(event: TraceEvent) -> TraceRow | None:
    """One trace event in plain words, or None for events not worth showing."""
    out, who = event.output, label(str(event.agent))
    if event.kind == "route":
        what = f"Sent to {label(out['agent'])} ({out['reason']})"
    elif event.kind == "retrieval":
        if out["confident"]:
            older = " (written for older readers)" if out.get("above_level") else ""
            what = f"Searched the articles. Best match: {out['articles'][0]}{older}"
        else:
            what = "Searched the articles. Nothing matched well enough"
    elif event.kind == "llm":
        if event.agent == "guardian":
            what = "Reviewed the draft with the fast model"
        elif out.get("tool_calls"):
            what = f"Asked to use: {', '.join(out['tool_calls'])}"
        else:
            what = "Wrote a draft"
    elif event.kind == "tool":
        what = f"Ran {event.name}" + (" (it reported an error)" if out.get("is_error") else "")
    elif event.kind == "error":
        what = f"Failed: {out['error']}"
    elif event.kind == "verdict":
        reasons = "; ".join(out["reasons"])
        what = "Approved" if out["approved"] else f"Not approved: {reasons}"
    elif event.kind == "fallback":
        what = "Used the safe fallback reply"
    else:
        return None  # "agent" and "respond" repeat what the rows around them already say
    return TraceRow(who=who, what=what, ms=f"{event.latency_ms} ms" if event.latency_ms else "")


def caption_for(result: TurnResult) -> str:
    if result.fallback_used:
        return "Penny could not get a checked answer, so she gave a safe reply."
    agent = label(result.route)
    if result.rewrites:
        times = "1 rewrite" if result.rewrites == 1 else f"{result.rewrites} rewrites"
        return f"Answered by {agent}. The Guardian asked for {times}, then approved it."
    return f"Answered by {agent}. Checked by the Guardian."


def build_turn(question: str, result: TurnResult, events: list[TraceEvent]) -> ChatTurn:
    rows = [row for row in (describe(e) for e in events) if row is not None]
    return ChatTurn(
        question=question,
        reply=result.reply,
        caption=caption_for(result),
        citations=result.citations,
        trace=rows,
    )


def citation_line(citation: Citation) -> str:
    """Markdown for one source: the article, then links to the pages its facts came from."""
    links = ", ".join(f"[{md(s.title)}]({s.url})" for s in citation.sources)
    return f"**{md(citation.title)}**" + (f" from {links}" if links else "")
