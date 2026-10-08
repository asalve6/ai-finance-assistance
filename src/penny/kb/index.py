"""A FAISS index over article chunks.

Only **reviewed** articles are indexed unless `include_drafts` is set, so a child never gets an
answer from an article the owner has not checked. The index is saved to disk with a content hash,
so a stale index (articles changed since it was built) can be detected.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import faiss
import numpy as np
from pydantic import BaseModel

from penny.contracts import Level
from penny.kb.article import KB_DIR, Article
from penny.kb.chunking import CHUNKER_VERSION, Chunk, chunk_article
from penny.kb.embedding import Embedder

INDEX_DIR = KB_DIR / "index"
_INDEX_FILE, _CHUNKS_FILE, _META_FILE = "index.faiss", "chunks.json", "meta.json"
LEVEL_ORDER = {Level.STARTER: 0, Level.SAVER: 1, Level.BUILDER: 2}


class IndexMismatchError(RuntimeError):
    """The saved index was built with a different embedder than the one asked for."""


class Hit(BaseModel):
    chunk: Chunk
    score: float


class IndexMeta(BaseModel):
    embedder: str
    dim: int
    content_hash: str
    include_drafts: bool
    chunk_count: int


def select_articles(articles: list[Article], include_drafts: bool) -> list[Article]:
    return [a for a in articles if include_drafts or a.reviewed]


def content_hash(articles: list[Article]) -> str:
    """Fingerprint of what the index was built from: the articles and the chunking rules."""
    digest = hashlib.sha256()
    digest.update(f"chunker:{CHUNKER_VERSION}\n".encode())
    for a in sorted(articles, key=lambda a: a.id):
        digest.update(f"{a.id}|{a.level}|{int(a.reviewed)}|{a.summary}|{a.body}\n".encode())
    return digest.hexdigest()


class KBIndex:
    def __init__(
        self, index: faiss.Index, chunks: list[Chunk], meta: IndexMeta, embedder: Embedder
    ) -> None:
        self._index = index
        self.chunks = chunks
        self.meta = meta
        self.embedder = embedder

    @classmethod
    def build(
        cls, articles: list[Article], embedder: Embedder, *, include_drafts: bool = False
    ) -> KBIndex:
        selected = select_articles(articles, include_drafts)
        chunks = [chunk for article in selected for chunk in chunk_article(article)]
        index = faiss.IndexFlatIP(embedder.dim)  # inner product == cosine on unit vectors
        if chunks:
            index.add(np.ascontiguousarray(embedder.embed([c.embed_text for c in chunks])))
        meta = IndexMeta(
            embedder=embedder.name,
            dim=embedder.dim,
            content_hash=content_hash(selected),
            include_drafts=include_drafts,
            chunk_count=len(chunks),
        )
        return cls(index, chunks, meta, embedder)

    def is_stale(self, articles: list[Article]) -> bool:
        selected = select_articles(articles, self.meta.include_drafts)
        return content_hash(selected) != self.meta.content_hash

    def search(
        self,
        query: str,
        *,
        k: int = 4,
        min_score: float | None = None,
        max_level: Level | None = None,
    ) -> list[Hit]:
        """Best chunks first. Chunks scoring below `min_score` (default: the embedder's own
        threshold) are dropped, and `max_level` hides articles harder than the reader's level."""
        total = self._index.ntotal
        if total == 0 or not query.strip():
            return []
        threshold = self.embedder.default_min_score if min_score is None else min_score
        scores, ids = self._index.search(np.ascontiguousarray(self.embedder.embed([query])), total)
        hits: list[Hit] = []
        for score, position in zip(scores[0], ids[0], strict=True):
            chunk = self.chunks[position]
            if float(score) < threshold:
                break  # scores are sorted, so nothing later can qualify
            if max_level and LEVEL_ORDER[chunk.level] > LEVEL_ORDER[max_level]:
                continue
            hits.append(Hit(chunk=chunk, score=float(score)))
            if len(hits) == k:
                break
        return hits

    def save(self, directory: Path = INDEX_DIR) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / _INDEX_FILE))
        chunks = [c.model_dump(mode="json") for c in self.chunks]
        (directory / _CHUNKS_FILE).write_text(json.dumps(chunks, indent=1))
        (directory / _META_FILE).write_text(self.meta.model_dump_json(indent=1))

    @classmethod
    def load(cls, embedder: Embedder, directory: Path = INDEX_DIR) -> KBIndex:
        meta = IndexMeta.model_validate_json((directory / _META_FILE).read_text())
        if meta.embedder != embedder.name or meta.dim != embedder.dim:
            raise IndexMismatchError(
                f"index was built with '{meta.embedder}', not '{embedder.name}'. Rebuild it."
            )
        raw_chunks = json.loads((directory / _CHUNKS_FILE).read_text())
        chunks = [Chunk.model_validate(c) for c in raw_chunks]
        index = faiss.read_index(str(directory / _INDEX_FILE))
        return cls(index, chunks, meta, embedder)
