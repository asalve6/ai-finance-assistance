"""Turn text into vectors. Two embedders share one small interface.

- `HashingEmbedder`: deterministic, word-based, needs no download. For tests, offline work and a
  last-resort demo mode. It matches on shared words, not meaning.
- `SentenceTransformerEmbedder`: the real semantic model (all-MiniLM-L6-v2). It needs the optional
  install `uv sync --extra embeddings` and downloads the model weights on first use.

Vectors are float32 and L2-normalised, so a dot product is cosine similarity.
"""

from __future__ import annotations

import re
import zlib
from typing import Any, Protocol

import numpy as np

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


def get_embedder(name: str) -> Embedder:
    """`hashing` (offline) or `minilm` (semantic)."""
    if name == "hashing":
        return HashingEmbedder()
    if name == "minilm":
        return SentenceTransformerEmbedder()
    raise ValueError(f"unknown embedder '{name}', expected 'hashing' or 'minilm'")
