"""Split articles into small, self-describing chunks for retrieval.

Each article becomes one chunk for its summary plus chunks for each `##` section. `Chunk.text`
keeps the author's structure (paragraph breaks, list items, fenced code), because that is what
gets shown to people and put into prompts. Only `Chunk.embed_text`, the string that is turned
into a vector, is flattened to plain prose.

A section that is longer than the limit is split between blocks (paragraphs, lists, code), never
in the middle of a list item, and a fenced code block is never split. Plain paragraphs that are
still too long are split on sentence boundaries. Every chunk keeps the article's title, level and
sources, so an answer built from it can always say where it came from.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from penny.contracts import Level
from penny.kb.article import Area, Article, Source

# Bump when the chunking rules change, so saved indexes built with older rules count as stale.
CHUNKER_VERSION = 2
MAX_CHUNK_WORDS = 120

_SENTENCE_BREAK = re.compile(r"(?<=[.!?:])\s+")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = "```"


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
        """What gets embedded: the title and heading give a short chunk its context, and the
        markdown is flattened to plain prose."""
        return f"{self.title}. {self.heading}. {_plain(self.text)}"


def _plain(text: str) -> str:
    text = re.sub(r"```\w*", " ", text)
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text, flags=re.MULTILINE)
    return " ".join(text.replace("**", " ").replace("`", " ").split())


def split_sections(body: str) -> list[tuple[str, str]]:
    """Returns (heading, text) pairs. Text before the first `##` heading is called Overview."""
    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    in_fence = False
    for line in body.splitlines():
        if line.strip().startswith(_FENCE):
            in_fence = not in_fence
        if line.startswith("## ") and not in_fence:
            sections.append((line[3:].strip(), []))
        else:
            sections[-1][1].append(line)
    cleaned = [(h, "\n".join(lines).strip()) for h, lines in sections]
    return [(h, t) for h, t in cleaned if t]


def _blocks(text: str) -> list[str]:
    """Paragraphs, lists and fenced code blocks, each keeping its own line breaks."""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current:
            blocks.append("\n".join(current))
            current.clear()

    for line in text.splitlines():
        if line.strip().startswith(_FENCE):
            if not in_fence:
                flush()
            current.append(line)
            in_fence = not in_fence
            if not in_fence:
                flush()
        elif in_fence:
            current.append(line)
        elif not line.strip():
            flush()
        else:
            current.append(line)
    flush()
    return blocks


def _pack(units: list[str], joiner: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    count = 0
    for unit in units:
        words = len(unit.split())
        if current and count + words > limit:
            pieces.append(joiner.join(current))
            current, count = [], 0
        current.append(unit)
        count += words
    if current:
        pieces.append(joiner.join(current))
    return pieces


def _split_block(block: str, limit: int) -> list[str]:
    """Split one oversized block without breaking its structure."""
    if block.lstrip().startswith(_FENCE):
        return [block]  # never split code
    lines = block.splitlines()
    if any(_LIST_ITEM.match(line) for line in lines):
        return _pack(lines, "\n", limit)
    sentences = [s.strip() for s in _SENTENCE_BREAK.split(" ".join(lines)) if s.strip()]
    return _pack(sentences, " ", limit)


def _section_pieces(text: str, limit: int) -> list[str]:
    units: list[str] = []
    for block in _blocks(text):
        if len(block.split()) > limit:
            units.extend(_split_block(block, limit))
        else:
            units.append(block)
    return _pack(units, "\n\n", limit)


def chunk_article(article: Article, max_words: int = MAX_CHUNK_WORDS) -> list[Chunk]:
    parts: list[tuple[str, str]] = [("Summary", article.summary)]
    for heading, text in split_sections(article.body):
        parts.extend((heading, piece) for piece in _section_pieces(text, max_words))
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
