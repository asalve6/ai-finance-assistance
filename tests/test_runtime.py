import pytest

from kb_helpers import corpus
from penny import runtime
from penny.agents.knowledge import KnowledgeAgent
from penny.contracts import LLMResponse
from penny.graph import demo
from penny.graph.stubs import StubSpecialist
from penny.graph.types import SPECIALISTS
from penny.kb.embedding import HashingEmbedder
from penny.kb.index import KBIndex
from penny.llm.errors import LLMError
from penny.llm.factory import LLMSetup
from penny.llm.fake import FakeLLM
from penny.observability import InMemoryTraceSink

INDEX = KBIndex.build(corpus(draft_bond=False), HashingEmbedder())


def setup(*responses: LLMResponse) -> LLMSetup:
    return LLMSetup(FakeLLM(list(responses)), "fake", "fast-model", "main-model")


def test_the_real_agents_are_wired_in_and_the_rest_stay_stubs():
    graph = runtime.build_penny(setup=setup(), index=INDEX)
    assert tuple(graph.agents) == SPECIALISTS
    for name, agent in graph.agents.items():
        expected = KnowledgeAgent if name in runtime.REAL_AGENTS else StubSpecialist
        assert isinstance(agent, expected), name


def test_finance_qa_uses_the_main_model_and_the_shared_trace_sink():
    sink = InMemoryTraceSink()
    llm_setup = setup(LLMResponse(text="A stock is a small piece of a company."))
    graph = runtime.build_penny(setup=llm_setup, index=INDEX, sink=sink)
    result = graph.ask("what is a stock", session_id="s")
    assert result.reply == "A stock is a small piece of a company."
    assert llm_setup.client.calls[0]["model"] == "main-model"
    kinds = [(e.agent, e.kind) for e in sink.for_trace(result.trace_id)]
    assert kinds == [
        ("router", "route"),
        ("finance_qa", "retrieval"),
        ("finance_qa", "llm"),
        ("finance_qa", "agent"),
        ("guardian", "verdict"),
        ("graph", "respond"),
    ]


def test_load_index_reads_the_saved_index_with_the_configured_embedder(tmp_path, monkeypatch):
    INDEX.save(tmp_path)
    monkeypatch.setattr(runtime, "INDEX_DIR", tmp_path)
    monkeypatch.setenv("KB_EMBEDDER", "hashing")
    assert runtime.load_index().meta == INDEX.meta


def test_load_index_fails_clearly_when_nothing_was_built(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "INDEX_DIR", tmp_path / "missing")
    monkeypatch.setenv("KB_EMBEDDER", "hashing")
    with pytest.raises(FileNotFoundError):
        runtime.load_index()


# ------------------------------------------------------------------ the demo's live mode


def test_the_live_demo_shows_the_answer_its_source_and_the_trace(monkeypatch, capsys):
    def fake_live(sink):
        llm_setup = setup(LLMResponse(text="A stock is a small piece of a company."))
        return runtime.build_penny(setup=llm_setup, index=INDEX, sink=sink)

    monkeypatch.setattr(demo, "_live_graph", fake_live)
    assert demo.main(["--live", "--level", "builder", "what is a stock"]) == 0
    out = capsys.readouterr().out
    assert "Penny: A stock is a small piece of a company." in out
    assert "source  What Is A Stock" in out
    assert "trace  finance_qa retrieval" in out


def test_the_live_demo_reports_the_safe_fallback(monkeypatch, capsys):
    class Down:
        def complete(self, **kwargs):
            raise LLMError("rate limited", retryable=True)

    def fake_live(sink):
        llm_setup = LLMSetup(Down(), "fake", "f", "m")
        return runtime.build_penny(setup=llm_setup, index=INDEX, sink=sink)

    monkeypatch.setattr(demo, "_live_graph", fake_live)
    assert demo.main(["--live", "what is a stock"]) == 0
    out = capsys.readouterr().out
    assert "safe fallback used: LLMError: rate limited" in out


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (FileNotFoundError(), "no article index found. Build one first: make kb-index"),
        (LLMError("OPENAI_API_KEY is not set."), "OPENAI_API_KEY is not set."),
        (RuntimeError("index was built with 'x'. Rebuild it."), "Rebuild it."),
    ],
)
def test_the_live_demo_explains_setup_problems_in_one_line(monkeypatch, capsys, error, message):
    def broken(sink):
        raise error

    monkeypatch.setattr(demo, "_live_graph", broken)
    assert demo.main(["--live", "hi"]) == 2
    out = capsys.readouterr().out.strip()
    assert out.startswith("Error: ") and message in out and "\n" not in out
