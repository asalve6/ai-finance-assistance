"""A specialist that answers only from Penny's own reviewed articles (RAG).

How one answer is produced:

1. The code searches the article index for the question. The reader's level is a preference, not
   a wall: articles at or below it are tried first, and only if nothing matches are harder
   articles used, with a note telling the model to explain them extra simply.
2. The model gets those passages and writes a short answer. It may search again, at most twice,
   through the `search_articles` tool, which helps with follow-ups such as "tell me more".
3. Grounding is enforced in code, not left to the model: if no search in this turn found a
   confident match, the model's text is discarded and a fixed "I don't know that yet" reply is
   returned. Greetings and thanks are the only exception.

The Finance Q&A agent (E1) and the Tax Education agent (E5) are two instances of this class,
built in `specialists.py`.
"""

from __future__ import annotations

import re
import time

from pydantic import BaseModel, Field

from penny.agents.loop import run_agent
from penny.agents.prompts import recent_history, system_prompt
from penny.agents.tools import make_tool
from penny.contracts import Level, LLMClient, Message, TraceEvent, TraceSink
from penny.graph.types import AgentReply, AgentRequest
from penny.kb.index import KBIndex
from penny.kb.retriever import Citation, Retrieval, retrieve
from penny.observability import NullTraceSink

NOT_SURE = (
    "I don't know that one yet. I only answer from what I have learned about money so far. "
    "Could you ask it another way, or try a different money question?"
)

OLDER_READER_NOTE = (
    "(These passages were written for older readers. Explain the idea in extra simple words.)"
)

MAX_TOOL_SEARCHES = 2
EVIDENCE_LIMIT = 6000  # characters of passages passed on to the Guardian
MAX_CITATIONS = 3
# Only cite articles that matched nearly as well as the best one, so weak side matches are not
# shown as sources.
CITATION_SCORE_RATIO = 0.75

_SMALL_TALK = re.compile(
    r"^(hi|hello|hey|yo|thanks|thank you|thx|bye|goodbye|ok|okay|cool|nice|"
    r"good (morning|afternoon|evening|night))\b[\sa-z!,.']*$"
)

_RULES = """\
How to answer:
- Answer ONLY from the article passages you are given or that search_articles returns. Do not use
  anything else you know, even if you are sure it is right.
- If the passages do not answer the question, say you do not know that yet.
- Write plain sentences and stay inside the sentence limit below. No lists, headings or bold.
- You may reuse a comparison from the passages. Do not invent new ones, and never make money sound
  like it grows by itself.
- If you say that money or a price can go up, also say that it can go down.
- This is for learning. Never tell the child what to buy, sell or invest in, and never promise
  that money will grow.
- Do not list sources or article ids. The app shows the sources.
- For a greeting or a thank-you, reply in one friendly sentence and invite a money question."""


def is_small_talk(text: str) -> bool:
    cleaned = text.strip().lower()
    return len(cleaned.split()) <= 4 and bool(_SMALL_TALK.match(cleaned))


class SearchArgs(BaseModel):
    query: str = Field(description="What to look for, in a few plain words", min_length=1)


class KnowledgeAgent:
    def __init__(
        self,
        llm: LLMClient,
        model: str,
        index: KBIndex,
        *,
        name: str = "finance_qa",
        role: str = "You answer children's questions about money.",
        closing_note: str | None = None,
        sink: TraceSink | None = None,
        max_steps: int = 4,
        max_tokens: int | None = 1200,
    ) -> None:
        self.llm = llm
        self.model = model
        self.index = index
        self.name = name
        self.role = role
        # A sentence that every grounded answer must end with (for example a disclaimer). It is
        # added in code if the model leaves it out, so it never depends on the model remembering.
        self.closing_note = closing_note
        self.sink = sink or NullTraceSink()
        self.max_steps = max_steps
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------ prompt

    def system_prompt(self, request: AgentRequest) -> str:
        return system_prompt(request, self.role, _RULES)

    @staticmethod
    def _passages(found: Retrieval, above_level: bool) -> str:
        if not found.confident:
            return "(no matching articles)"
        note = f"{OLDER_READER_NOTE}\n" if above_level else ""
        return note + found.as_prompt_context()

    # ------------------------------------------------------------------ one answer

    def respond(self, request: AgentRequest) -> AgentReply:
        level = request.kid.level
        confident: list[Retrieval] = []
        searches = 0

        def search(query: str) -> tuple[Retrieval, bool]:
            """Returns (what was found, whether it came from above the reader's level)."""
            started = time.perf_counter()
            found = retrieve(self.index, query, max_level=level)
            above_level = False
            if not found.confident and level is not Level.BUILDER:
                wider = retrieve(self.index, query)  # nothing at their level: try every level
                if wider.confident:
                    found, above_level = wider, True
            if found.confident:
                confident.append(found)
            self.sink.record(
                TraceEvent(
                    trace_id=request.trace_id,
                    agent=self.name,
                    kind="retrieval",
                    name="search_articles",
                    input={"query": query, "max_level": level.value},
                    output={
                        "confident": found.confident,
                        "reason": found.reason,
                        "top_score": round(found.top_score, 3),
                        "articles": [c.article_id for c in found.citations()],
                        "above_level": above_level,
                    },
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            return found, above_level

        def search_tool(query: str) -> str:
            nonlocal searches
            if searches >= MAX_TOOL_SEARCHES:
                return "Search limit reached. Answer from what you have, or say you do not know."
            searches += 1
            found, above_level = search(query)
            if not found.confident:
                return "No articles matched. If nothing else helps, say you do not know that yet."
            return self._passages(found, above_level)

        tool = make_tool(
            "search_articles",
            "Search Penny's own library of kid-level money articles. Call it when the passages you "
            "were given do not answer the question: use different or simpler words, and for a "
            "follow-up include the topic from earlier in the conversation. Do not call it for "
            f"greetings. At most {MAX_TOOL_SEARCHES} searches.",
            SearchArgs,
            search_tool,
        )

        first, first_above_level = search(request.question)
        history = recent_history(request)
        passages = self._passages(first, first_above_level)
        prompt = f"Question: {request.question}\n\nArticle passages:\n{passages}"
        result = run_agent(
            self.llm,
            model=self.model,
            system=self.system_prompt(request),
            messages=[*history, Message.user(prompt)],
            tools=[tool],
            sink=self.sink,
            trace_id=request.trace_id,
            agent=self.name,
            max_steps=self.max_steps,
            max_tokens=self.max_tokens,
        )

        if not confident:
            if is_small_talk(request.question):
                return AgentReply(text=result.text.strip())
            return AgentReply(text=NOT_SURE)  # grounding enforced here, whatever the model wrote
        text = result.text.strip()
        if self.closing_note and self.closing_note.lower() not in text.lower():
            text = f"{text} {self.closing_note}"
        evidence = "\n\n".join(dict.fromkeys(r.as_prompt_context() for r in confident))
        return AgentReply(
            text=text, citations=self._citations(confident), evidence=evidence[:EVIDENCE_LIMIT]
        )

    @staticmethod
    def _citations(found: list[Retrieval]) -> list[Citation]:
        best: dict[str, tuple[float, Citation]] = {}
        for retrieval in found:
            scores = {h.chunk.article_id: h.score for h in reversed(retrieval.hits)}
            for citation in retrieval.citations():
                score = scores[citation.article_id]
                if citation.article_id not in best or score > best[citation.article_id][0]:
                    best[citation.article_id] = (score, citation)
        ranked = sorted(best.values(), key=lambda pair: pair[0], reverse=True)
        cutoff = ranked[0][0] * CITATION_SCORE_RATIO
        return [citation for score, citation in ranked[:MAX_CITATIONS] if score >= cutoff]
