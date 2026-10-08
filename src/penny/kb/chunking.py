"""Split articles into small, self-describing chunks for retrieval.

Each article becomes one chunk for its summary plus one chunk per `##` section. A long section is
split on sentence boundaries. Every chunk keeps the article's title, level and sources, so an
answer built from it can always say where it came from.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from penny.contracts import Level
from penny.kb.article import Area, Article, Source

MAX_CHUNK_WORDS = 120

_SENTENCE_BREAK = re.compile(r"(?<=[.!?:])\s+|\n+")


class Chunk(BaseModel):
    id: str  # "<article id>#<number>"
    article_id: str
    title: str
    area: Area
    level: Level
    heading: str
    text: str
    sources: list[Source]

    @property
    def embed_text(self) -> str:
        """What gets embedded: the title and heading give a short chunk its context."""
        return f"{self.title}. {self.heading}. {self.text}"


def split_sections(body: str) -> list[tuple[str, str]]:
    """Returns (heading, text) pairs. Text before the first `##` heading is called Overview."""
    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    for line in body.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        else:
            sections[-1][1].append(line)
    cleaned = [(h, "\n".join(lines).strip()) for h, lines in sections]
    return [(h, t) for h, t in cleaned if t]


def _split_long(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in (s.strip() for s in _SENTENCE_BREAK.split(text) if s.strip()):
        words = len(sentence.split())
        if current and count + words > limit:
            pieces.append(" ".join(current))
            current, count = [], 0
        current.append(sentence)
        count += words
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_article(article: Article, max_words: int = MAX_CHUNK_WORDS) -> list[Chunk]:
    parts: list[tuple[str, str]] = [("Summary", article.summary)]
    for heading, text in split_sections(article.body):
        if len(text.split()) <= max_words:
            parts.append((heading, " ".join(text.split())))
        else:
            parts.extend((heading, piece) for piece in _split_long(text, max_words))
    return [
        Chunk(
            id=f"{article.id}#{number}",
            article_id=article.id,
            title=article.title,
            area=article.area,
            level=article.level,
            heading=heading,
            text=text,
            sources=article.sources,
        )
        for number, (heading, text) in enumerate(parts)
    ]
