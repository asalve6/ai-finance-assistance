import numpy as np
import pytest

from penny.kb.embedding import (
    MINILM_DIM,
    HashingEmbedder,
    SentenceTransformerEmbedder,
    get_embedder,
)


def cosine(embedder, a: str, b: str) -> float:
    va, vb = embedder.embed([a, b])
    return float(va @ vb)


def test_hashing_vectors_are_normalised_float32_and_deterministic():
    embedder = HashingEmbedder()
    first = embedder.embed(["Saving money in a piggy bank", "What is a stock?"])
    again = embedder.embed(["Saving money in a piggy bank", "What is a stock?"])
    assert first.shape == (2, embedder.dim)
    assert first.dtype == np.float32
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-5)
    assert np.array_equal(first, again)


def test_hashing_ranks_related_text_above_unrelated_text():
    embedder = HashingEmbedder()
    question = "how does a piggy bank help me save money"
    related = cosine(embedder, question, "A piggy bank helps you save")
    unrelated = cosine(embedder, question, "Shares trade on an exchange")
    assert related > unrelated
    assert unrelated < embedder.default_min_score <= related


def test_hashing_handles_empty_and_stopword_only_text_without_nan():
    vectors = HashingEmbedder().embed(["", "the and of", "!!!"])
    assert not np.isnan(vectors).any()
    assert np.count_nonzero(vectors) == 0


def test_hashing_empty_batch():
    assert HashingEmbedder().embed([]).shape == (0, HashingEmbedder.dim)


class FakeModel:
    """Stands in for the real model so tests never download anything."""

    def __init__(self):
        self.calls = []

    def encode(self, texts, normalize_embeddings, convert_to_numpy):
        self.calls.append((list(texts), normalize_embeddings, convert_to_numpy))
        return np.tile(np.arange(1, MINILM_DIM + 1, dtype=np.float64), (len(texts), 1))


def test_sentence_transformer_embedder_uses_the_injected_model_and_renormalises():
    model = FakeModel()
    embedder = SentenceTransformerEmbedder(model=model)
    vectors = embedder.embed(["one", "two"])
    assert model.calls == [(["one", "two"], True, True)]
    assert vectors.shape == (2, MINILM_DIM) and vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_sentence_transformer_embedder_empty_batch_does_not_load_a_model():
    embedder = SentenceTransformerEmbedder()
    assert embedder.embed([]).shape == (0, MINILM_DIM)


def test_missing_optional_install_gives_a_helpful_message(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def block(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block)
    with pytest.raises(RuntimeError, match="uv sync --extra embeddings"):
        SentenceTransformerEmbedder().embed(["hello"])


def test_get_embedder_by_name():
    assert isinstance(get_embedder("hashing"), HashingEmbedder)
    assert isinstance(get_embedder("minilm"), SentenceTransformerEmbedder)
    with pytest.raises(ValueError, match="unknown embedder"):
        get_embedder("nope")
