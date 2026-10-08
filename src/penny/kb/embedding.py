"""Turn text into vectors. Three embedders share one small interface.

- `OpenAIEmbedder` (the default): OpenAI text-embedding-3-small, semantic. Needs OPENAI_API_KEY.
- `HashingEmbedder`: deterministic, word-based, needs no download or key. For tests and offline
  work. It matches on shared words, not meaning.
- `SentenceTransformerEmbedder`: a local semantic model (all-MiniLM-L6-v2). It needs the optional
  install `uv sync --extra embeddings` and downloads the model weights on first use.

Vectors are float32 and L2-normalised, so a dot product is cosine similarity.
"""

from __future__ import annotations

import os
import re
import zlib
from typing import Any, Protocol

import numpy as np

DEFAULT_EMBEDDER = "openai"
OPENAI_MODEL = "text-embedding-3-small"
OPENAI_DIM = 1536
MINILM_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MINILM_DIM = 384

_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have how i if in is it its of on or so that the "
    "their then there they this to was we what when where which who why will with you your do does "
    "can not no yes".split()
)


class Embedder(Protocol):
    name: str
    dim: int
    # Cosine score below which a search result is treated as "not a real match".
    default_min_score: float

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class HashingEmbedder:
    name = "hashing-512"
    dim = 512
    default_min_score = 0.2

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.lower()):
                if len(word) < 2 or word in _STOPWORDS:
                    continue
                matrix[row, zlib.crc32(word.encode()) % self.dim] += 1.0
        return _normalise(np.sqrt(matrix))


class SentenceTransformerEmbedder:
    name = MINILM_NAME
    dim = MINILM_DIM
    default_min_score = 0.30  # provisional: calibrate against real questions once installed

    def __init__(self, model: Any = None) -> None:
        self._model = model  # injectable so tests never download anything

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "The semantic embedder is not installed. Run: uv sync --extra embeddings "
                    "(downloads PyTorch and the all-MiniLM-L6-v2 model on first use)."
                ) from exc
            self._model = SentenceTransformer(MINILM_NAME)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self._load().encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return _normalise(np.asarray(vectors, dtype=np.float32))


class OpenAIEmbedder:
    """OpenAI's text-embedding-3-small. Needs OPENAI_API_KEY and the network.

    Each question a child asks is sent to OpenAI to be embedded. Repeated texts are remembered, so
    asking the same thing twice costs no second call. Blank texts become zero vectors without
    calling the API (it rejects empty input).
    """

    name = f"openai/{OPENAI_MODEL}"
    dim = OPENAI_DIM
    default_min_score = 0.30  # provisional: calibrate against real questions

    def __init__(self, client: Any = None, *, batch_size: int = 100, cache_size: int = 512) -> None:
        self._client = client
        self._batch_size = batch_size
        self._cache_size = cache_size
        self._cache: dict[str, np.ndarray] = {}

    def _api(self) -> Any:
        if self._client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError(
                    "OPENAI_API_KEY is not set. Add it to .env (see .env.example) or use "
                    "--embedder hashing for the offline test embedder."
                )
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def _remember(self, text: str, vector: np.ndarray) -> None:
        if len(self._cache) >= self._cache_size:
            self._cache.pop(next(iter(self._cache)))  # drop the oldest
        self._cache[text] = vector

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        unique = list(dict.fromkeys(t for t in texts if t.strip() and t not in self._cache))
        fetched: dict[str, np.ndarray] = {}
        for start in range(0, len(unique), self._batch_size):
            batch = unique[start : start + self._batch_size]
            response = self._api().embeddings.create(model=OPENAI_MODEL, input=batch)
            for item in sorted(response.data, key=lambda d: d.index):
                fetched[batch[item.index]] = _normalise(
                    np.asarray([item.embedding], dtype=np.float32)
                )[0]
        for row, text in enumerate(texts):
            if text.strip():
                # Read from this call's own results first: the bounded cache may already have
                # evicted a text that was fetched earlier in the same call.
                matrix[row] = fetched[text] if text in fetched else self._cache[text]
        for text, vector in fetched.items():
            self._remember(text, vector)
        return matrix


def get_embedder(name: str = DEFAULT_EMBEDDER) -> Embedder:
    """`openai` (default), `minilm` (local semantic), or `hashing` (offline, for tests)."""
    if name == "openai":
        return OpenAIEmbedder()
    if name == "hashing":
        return HashingEmbedder()
    if name == "minilm":
        return SentenceTransformerEmbedder()
    raise ValueError(f"unknown embedder '{name}', expected 'openai', 'minilm' or 'hashing'")
