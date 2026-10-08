import zlib
from types import SimpleNamespace

import numpy as np
import pytest

from penny.config import load_env
from penny.kb import ask, build
from penny.kb.embedding import (
    DEFAULT_EMBEDDER,
    OPENAI_DIM,
    HashingEmbedder,
    OpenAIEmbedder,
    get_embedder,
)
from penny.kb.index import IndexMismatchError, KBIndex


def vector_for(text: str) -> list[float]:
    """A stable pseudo-embedding, so the same text always gets the same vector."""
    return np.random.default_rng(zlib.crc32(text.encode())).normal(size=OPENAI_DIM).tolist()


class FakeOpenAI:
    """Mimics client.embeddings.create(model=..., input=[...]) and returns rows out of order,
    as an API is allowed to."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.embeddings = self

    def create(self, *, model: str, input: list[str]):
        self.calls.append((model, list(input)))
        data = [SimpleNamespace(index=i, embedding=vector_for(t)) for i, t in enumerate(input)]
        return SimpleNamespace(data=list(reversed(data)))


def test_openai_is_the_default_embedder():
    assert DEFAULT_EMBEDDER == "openai"
    assert isinstance(get_embedder(), OpenAIEmbedder)
    assert isinstance(get_embedder("openai"), OpenAIEmbedder)


def test_vectors_are_float32_unit_length_and_match_their_inputs_despite_reordering():
    client = FakeOpenAI()
    embedder = OpenAIEmbedder(client)
    vectors = embedder.embed(["piggy bank", "stock market", "taxes"])
    assert vectors.shape == (3, OPENAI_DIM) and vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
    for row, text in enumerate(["piggy bank", "stock market", "taxes"]):
        expected = np.asarray(vector_for(text), dtype=np.float32)
        expected /= np.linalg.norm(expected)
        assert np.allclose(vectors[row], expected, atol=1e-5)


def test_the_request_uses_the_small_embedding_model():
    client = FakeOpenAI()
    OpenAIEmbedder(client).embed(["hello"])
    assert client.calls == [("text-embedding-3-small", ["hello"])]
    assert OpenAIEmbedder.name == "openai/text-embedding-3-small"


def test_large_inputs_are_sent_in_batches():
    client = FakeOpenAI()
    OpenAIEmbedder(client, batch_size=2).embed([f"text {n}" for n in range(5)])
    assert [len(batch) for _, batch in client.calls] == [2, 2, 1]


def test_repeated_texts_are_embedded_once():
    client = FakeOpenAI()
    embedder = OpenAIEmbedder(client)
    first = embedder.embed(["what is a stock", "what is a stock", "taxes"])
    again = embedder.embed(["what is a stock"])
    assert len(client.calls) == 1
    assert client.calls[0][1] == ["what is a stock", "taxes"]
    assert np.array_equal(first[0], first[1]) and np.array_equal(first[0], again[0])


def test_the_cache_is_bounded_and_forgets_the_oldest_text():
    client = FakeOpenAI()
    embedder = OpenAIEmbedder(client, cache_size=2)
    embedder.embed(["a text", "b text", "c text"])
    assert len(embedder._cache) == 2
    client.calls.clear()
    embedder.embed(["a text"])  # was evicted, so it must be fetched again
    assert len(client.calls) == 1


def test_blank_texts_become_zero_vectors_without_calling_the_api():
    client = FakeOpenAI()
    vectors = OpenAIEmbedder(client).embed(["", "   ", "real text"])
    assert client.calls == [("text-embedding-3-small", ["real text"])]
    assert not vectors[0].any() and not vectors[1].any() and vectors[2].any()


def test_an_empty_batch_needs_no_client_or_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAIEmbedder().embed([]).shape == (0, OPENAI_DIM)


def test_a_missing_key_gives_a_helpful_message(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"OPENAI_API_KEY.*\.env"):
        OpenAIEmbedder().embed(["hello"])


def test_the_real_client_is_created_lazily_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    embedder = OpenAIEmbedder()
    assert embedder._client is None
    assert embedder._api().__class__.__name__ == "OpenAI"


def test_an_index_built_with_openai_vectors_works_and_refuses_other_embedders(tmp_path):
    from kb_helpers import corpus

    embedder = OpenAIEmbedder(FakeOpenAI())
    index = KBIndex.build(corpus(), embedder)
    assert index.meta.embedder == "openai/text-embedding-3-small" and index.meta.dim == OPENAI_DIM
    index.save(tmp_path)
    assert KBIndex.load(embedder, tmp_path).meta == index.meta
    with pytest.raises(IndexMismatchError):
        KBIndex.load(HashingEmbedder(), tmp_path)


def test_load_env_reads_a_dotenv_file_but_never_overrides_real_variables(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PENNY_TEST_FROM_FILE=file\nPENNY_TEST_ALREADY_SET=file\n")
    monkeypatch.delenv("PENNY_TEST_FROM_FILE", raising=False)
    monkeypatch.setenv("PENNY_TEST_ALREADY_SET", "real")
    assert load_env(env_file) is True
    import os

    assert os.environ["PENNY_TEST_FROM_FILE"] == "file"
    assert os.environ["PENNY_TEST_ALREADY_SET"] == "real"
    monkeypatch.delenv("PENNY_TEST_FROM_FILE")


def test_commands_honour_kb_embedder_from_the_environment(tmp_path, monkeypatch, capsys):
    from kb_helpers import corpus, write_articles

    monkeypatch.setenv("KB_EMBEDDER", "hashing")
    write_articles(tmp_path / "kb", corpus())
    out = tmp_path / "idx"
    assert build.main(["--dir", str(tmp_path / "kb"), "--out", str(out)]) == 0
    assert "hashing-512" in capsys.readouterr().out
    assert ask.main(["what is a stock", "--index", str(out)]) == 0
    assert "what-is-a-stock" in capsys.readouterr().out


def test_env_example_parses_cleanly_and_defaults_to_openai_embeddings():
    from dotenv import dotenv_values

    from penny.config import PROJECT_ROOT

    values = dotenv_values(PROJECT_ROOT / ".env.example")
    assert values["KB_EMBEDDER"] == DEFAULT_EMBEDDER == "openai"
    assert values["OPENAI_API_KEY"] == ""  # no secret, and no inline comment read as a value
    assert not [k for k, v in values.items() if v and "#" in v]


def test_commands_show_a_clean_error_instead_of_a_traceback(tmp_path, monkeypatch, capsys):
    from kb_helpers import corpus, write_articles

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KB_EMBEDDER", raising=False)
    write_articles(tmp_path / "kb", corpus())
    out = tmp_path / "idx"
    base = ["--dir", str(tmp_path / "kb"), "--out", str(out)]

    assert build.main([*base, "--include-drafts", "--embedder", "openai"]) == 2
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().out
    assert build.main([*base, "--embedder", "nope"]) == 2
    assert "unknown embedder" in capsys.readouterr().out

    assert ask.main(["stock", "--index", str(out), "--embedder", "hashing"]) == 2
    assert "No index found" in capsys.readouterr().out

    build.main([*base, "--embedder", "hashing"])
    capsys.readouterr()
    assert ask.main(["stock", "--index", str(out), "--embedder", "openai"]) == 2
    assert "Rebuild it" in capsys.readouterr().out


def test_the_default_dotenv_is_skipped_under_test_but_an_explicit_path_still_loads(
    tmp_path, monkeypatch
):
    import os

    from penny import config

    (tmp_path / ".env").write_text("PENNY_TEST_DEFAULT_PATH=loaded\n")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("PENNY_TEST_DEFAULT_PATH", raising=False)

    assert config.load_env() is False  # the autouse fixture set PENNY_NO_DOTENV
    assert "PENNY_TEST_DEFAULT_PATH" not in os.environ

    monkeypatch.delenv("PENNY_NO_DOTENV")
    assert config.load_env() is True  # without the flag, the project .env is read
    assert os.environ["PENNY_TEST_DEFAULT_PATH"] == "loaded"
    monkeypatch.delenv("PENNY_TEST_DEFAULT_PATH")
