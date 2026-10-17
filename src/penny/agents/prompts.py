"""Prompt pieces every writer agent shares, so they all sound like one Penny."""

from __future__ import annotations

from penny.contracts import Level, Message
from penny.graph.stubs import MAX_SENTENCES
from penny.graph.types import AgentRequest
from penny.principles import voice_block

HISTORY_MESSAGES = 6

LEVEL_STYLE = {
    Level.STARTER: "Use very simple words and 2 to 4 short sentences. Explain any money word.",
    Level.SAVER: "Use simple words and 3 to 5 short sentences. Explain new money words briefly.",
    Level.BUILDER: "Use 3 to 6 sentences. You can use the correct money terms, with a quick "
    "explanation the first time.",
}


def system_prompt(request: AgentRequest, role: str, rules: str) -> str:
    """Who Penny is, her values, this agent's rules, the reader's level, and (on a rewrite) what
    the safety reviewer asked to be fixed."""
    parts = [
        f"You are Penny, a friendly money coach for a child called {request.kid.nickname}. {role}",
        voice_block(),
        rules,
        f"Reading level: {LEVEL_STYLE[request.kid.level]} Hard limit: never more than "
        f"{MAX_SENTENCES[request.kid.level]} sentences, or the reply is rejected.",
    ]
    if request.also_ask:
        parts.append(
            "The question has another part that a different helper will answer next: "
            f'"{request.also_ask}". Answer only the rest, and do not answer that part.'
        )
    if request.feedback:
        problems = "\n".join(f"- {item}" for item in request.feedback)
        parts.append(
            "Your previous draft was not accepted by the safety reviewer. Write a new answer "
            f"that fixes these problems:\n{problems}"
        )
    return "\n\n".join(parts)


def recent_history(request: AgentRequest) -> list[Message]:
    """The last few text turns of the session, without tool traffic or provider-private data."""
    return [
        Message(role=m.role, content=m.content)
        for m in request.history[-HISTORY_MESSAGES:]
        if m.role in ("user", "assistant") and m.content
    ]
