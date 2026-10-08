"""Retrieval for the Q&A agents: the best chunks, a confidence flag and citations.

`confident` is False when nothing scores above the threshold. The agent must then say it does not
know, instead of answering from its own memory.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from penny.contracts import Level
from penny.kb.article import Source
from penny.kb.index import Hit, KBIndex


class Citation(BaseModel):
    article_id: str
    title: str
    sources: list[Source]


class Retrieval(BaseModel):
    query: str
    hits: list[Hit]
    confident: bool
    top_score: float
    reason: Literal["ok", "no_match", "empty_index"]

    def citations(self) -> list[Citation]:
        """One citation per article, best match first."""
        seen: dict[str, Citation] = {}
        for hit in self.hits:
            seen.setdefault(
                hit.chunk.article_id,
                Citation(
                    article_id=hit.chunk.article_id,
                    title=hit.chunk.title,
                    sources=hit.chunk.sources,
                ),
            )
        return list(seen.values())

    def as_prompt_context(self) -> str:
        """The retrieved text, labelled by article id, for the agent's prompt."""
        return "\n\n".join(
            f"[{hit.chunk.article_id}] {hit.chunk.title} / {hit.chunk.heading}\n{hit.chunk.text}"
            for hit in self.hits
        )


def retrieve(
    index: KBIndex,
    query: str,
    *,
    k: int = 4,
    max_level: Level | None = None,
    min_score: float | None = None,
) -> Retrieval:
    hits = index.search(query, k=k, min_score=min_score, max_level=max_level)
    if hits:
        reason = "ok"
    elif index.meta.chunk_count == 0:
        reason = "empty_index"
    else:
        reason = "no_match"
    return Retrieval(
        query=query,
        hits=hits,
        confident=bool(hits),
        top_score=hits[0].score if hits else 0.0,
        reason=reason,
    )
