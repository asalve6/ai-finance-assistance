import pytest

from kb_helpers import corpus
from penny.agents.coach import CoachAgent
from penny.agents.knowledge import KnowledgeAgent
from penny.contracts import Level, LLMResponse, ToolCall, TraceEvent
from penny.graph.build import PennyGraph
from penny.graph.stubs import SAFE_FALLBACK, default_agents
from penny.graph.types import TurnResult
from penny.kb.article import Source
from penny.kb.embedding import HashingEmbedder
from penny.kb.index import KBIndex
from penny.kb.retriever import Citation
from penny.llm.errors import LLMError
from penny.llm.factory import LLMSetup
from penny.llm.fake import FakeLLM
from penny.observability import InMemoryTraceSink
from penny.ui import backend as backend_module
from penny.ui.backend import Backend, load_backend, missing_setup
from penny.ui.chat import ask
from penny.ui.chat_model import (
    GREETING,
    SUGGESTIONS,
    build_turn,
    caption_for,
    citation_line,
    describe,
    label,
)
from penny.ui.session import Player
from ui_helpers import click, launch

INDEX = KBIndex.build(corpus(draft_bond=False), HashingEmbedder())
STARTED = {"started": True, "nickname": "Sam", "level": Level.BUILDER}


def event(who, kind, name="", latency_ms=0, **output) -> TraceEvent:
    return TraceEvent(
        trace_id="t", agent=who, kind=kind, name=name, output=output, latency_ms=latency_ms
    )


def result(**overrides) -> TurnResult:
    base = {
        "reply": "A stock is a slice.",
        "route": "finance_qa",
        "route_reason": "default",
        "approved": True,
        "rewrites": 0,
        "fallback_used": False,
        "trace_id": "t",
    }
    return TurnResult(**{**base, **overrides})


# ------------------------------------------------------------------ trace rows in plain words


@pytest.mark.parametrize(
    ("trace_event", "who", "what", "ms"),
    [
        (event("router", "route", agent="tax", reason="matched 'paycheck'"), "Router", "Sent to Tax Education (matched 'paycheck')", ""),
        (event("finance_qa", "retrieval", latency_ms=210, confident=True, articles=["what-is-a-stock"], above_level=False), "Finance Q&A", "Searched the articles. Best match: what-is-a-stock", "210 ms"),
        (event("finance_qa", "retrieval", confident=True, articles=["what-is-a-bond"], above_level=True), "Finance Q&A", "Searched the articles. Best match: what-is-a-bond (written for older readers)", ""),
        (event("tax", "retrieval", confident=False, articles=[]), "Tax Education", "Searched the articles. Nothing matched well enough", ""),
        (event("coach", "llm", "gpt-4o", 1431, tool_calls=["plan_goal"], text=""), "Goal and Game Coach", "Asked to use: plan_goal", "1431 ms"),
        (event("coach", "llm", "gpt-4o", 950, tool_calls=[], text="Save..."), "Goal and Game Coach", "Wrote a draft", "950 ms"),
        (event("guardian", "llm", "gpt-4o-mini", 527, text="{}", parsed=True), "Guardian", "Reviewed the draft with gpt-4o-mini", "527 ms"),
        (event("guardian", "llm", "", 5, text="{}", parsed=True), "Guardian", "Reviewed the draft", "5 ms"),
        (event("coach", "tool", "plan_goal", result="{}", is_error=False), "Goal and Game Coach", "Ran plan_goal", ""),
        (event("coach", "tool", "plan_goal", result="x", is_error=True), "Goal and Game Coach", "Ran plan_goal (it reported an error)", ""),
        (event("finance_qa", "error", error="boom"), "Finance Q&A", "Failed: boom", ""),
        (event("guardian", "verdict", approved=True, reasons=[]), "Guardian", "Approved", ""),
        (event("guardian", "verdict", approved=False, reasons=["too long", "say it can fall"]), "Guardian", "Not approved: too long; say it can fall", ""),
        (event("graph", "fallback", rewrites=3), "Penny", "Used the safe fallback reply", ""),
    ],
)  # fmt: skip
def test_each_kind_of_trace_event_reads_as_a_plain_sentence(trace_event, who, what, ms):
    row = describe(trace_event)
    assert (row.who, row.what, row.ms) == (who, what, ms)


def test_bookkeeping_events_are_left_out_and_unknown_agents_keep_their_name():
    assert describe(event("finance_qa", "agent", chars=10)) is None
    assert describe(event("graph", "respond", approved=True)) is None
    assert label("some_new_agent") == "some_new_agent"


@pytest.mark.parametrize(
    ("overrides", "caption"),
    [
        ({}, "Answered by Finance Q&A. Checked by the Guardian."),
        ({"route": "coach"}, "Answered by Goal and Game Coach. Checked by the Guardian."),
        ({"rewrites": 1}, "Answered by Finance Q&A. The Guardian asked for 1 rewrite, then approved it."),
        ({"rewrites": 2}, "Answered by Finance Q&A. The Guardian asked for 2 rewrites, then approved it."),
        ({"fallback_used": True, "approved": False, "rewrites": 3}, "Penny could not get a checked answer, so she gave a safe reply."),
    ],
)  # fmt: skip
def test_the_caption_says_who_answered_and_how_it_was_checked(overrides, caption):
    assert caption_for(result(**overrides)) == caption


def test_a_source_line_links_the_pages_the_facts_came_from():
    citation = Citation(
        article_id="x",
        title="Saving $5 a week",
        sources=[
            Source(title="CFPB", url="https://a.example"),
            Source(title="FDIC", url="https://b.example"),
        ],
    )
    assert citation_line(citation) == (
        "**Saving \\$5 a week** from [CFPB](https://a.example), [FDIC](https://b.example)"
    )
    assert citation_line(Citation(article_id="y", title="No links", sources=[])) == "**No links**"


def test_build_turn_keeps_the_readable_rows_in_order():
    events = [
        event("router", "route", agent="finance_qa", reason="default"),
        event("finance_qa", "agent", chars=5),
        event("guardian", "verdict", approved=True, reasons=[]),
        event("graph", "respond", approved=True),
    ]
    turn = build_turn("what is a stock", result(), events)
    assert (turn.question, turn.reply) == ("what is a stock", "A stock is a slice.")
    assert [r.who for r in turn.trace] == ["Router", "Guardian"]


# ------------------------------------------------------------------ live or offline


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "KB_EMBEDDER"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_missing_setup_names_what_to_fix(clean_env):
    assert missing_setup() == "ANTHROPIC_API_KEY is not set in .env"
    clean_env.setenv("ANTHROPIC_API_KEY", "x")
    assert "OPENAI_API_KEY is not set in .env (it is needed to search" in missing_setup()
    clean_env.setenv("KB_EMBEDDER", "hashing")
    assert missing_setup() is None
    clean_env.setenv("LLM_PROVIDER", "OpenAI")
    assert missing_setup() == "OPENAI_API_KEY is not set in .env"
    clean_env.setenv("OPENAI_API_KEY", "x")
    assert missing_setup() is None


def test_without_keys_the_app_gets_the_offline_backend_that_still_answers(clean_env):
    backend = load_backend()
    assert backend.live is False and "ANTHROPIC_API_KEY" in backend.note
    assert backend.market.name == "chain"  # prices need no LLM key, so they stay real offline
    answer = backend.graph.ask("what is a stock", session_id="s")
    assert answer.reply.startswith("[finance_qa] stub answer")


def test_with_everything_set_the_backend_is_live(clean_env):
    clean_env.setenv("ANTHROPIC_API_KEY", "x")
    clean_env.setenv("KB_EMBEDDER", "hashing")
    setup = LLMSetup(FakeLLM([]), "anthropic", "fast-m", "main-m")
    clean_env.setattr(backend_module, "get_llm", lambda: setup)
    given = {}

    def build(setup, sink, market):
        given["market"] = market
        return PennyGraph(sink=sink)

    clean_env.setattr(backend_module, "build_penny", build)
    backend = load_backend()
    assert (backend.live, backend.note) == (True, "anthropic, main-m")
    assert backend.graph.sink is backend.sink
    assert backend.market is given["market"]  # the agents and the tab share one price cache


@pytest.mark.parametrize(
    ("error", "note"),
    [
        (FileNotFoundError(), "the article index has not been built yet (run: make kb-index)"),
        (LLMError("LLM_MODEL_MAIN looks wrong"), "LLM_MODEL_MAIN looks wrong"),
        (RuntimeError("index was built with another embedder"), "index was built with another embedder"),
    ],
)  # fmt: skip
def test_setup_problems_fall_back_to_offline_with_the_reason(clean_env, error, note):
    clean_env.setenv("ANTHROPIC_API_KEY", "x")
    clean_env.setenv("KB_EMBEDDER", "hashing")

    def broken(setup, sink, market):
        raise error

    clean_env.setattr(backend_module, "get_llm", lambda: LLMSetup(FakeLLM([]), "a", "f", "m"))
    clean_env.setattr(backend_module, "build_penny", broken)
    backend = load_backend()
    assert (backend.live, backend.note) == (False, note)


# ------------------------------------------------------------------ the Chat tab, running


def says(text: str) -> LLMResponse:
    return LLMResponse(text=text)


APPROVED = LLMResponse(text='{"approved": true, "problems": []}')


def live_backend(*responses: LLMResponse) -> Backend:
    """The real agents and graph, with a scripted model and a word-matching index."""
    sink = InMemoryTraceSink()
    llm = FakeLLM(list(responses))
    agents = {
        **default_agents(),
        "finance_qa": KnowledgeAgent(llm, "main-m", INDEX, sink=sink),
        "coach": CoachAgent(llm, "main-m", sink=sink),
    }
    return Backend(PennyGraph(agents=agents, sink=sink), sink, True, "fake, main-m")


def messages(app):
    return [(m.name, m.markdown[0].value) for m in app.chat_message]


def test_the_chat_opens_with_a_greeting_and_suggestions():
    app = launch(player=Player(**STARTED))
    assert messages(app) == [("assistant", GREETING)]
    labels = [b.label for b in app.button]
    assert all(s.replace("$", "\\$") in labels for s in SUGGESTIONS)
    assert app.chat_input[0].placeholder == "Ask Penny a money question"


def test_offline_mode_says_why_and_a_live_backend_shows_no_banner():
    offline = launch(player=Player(**STARTED))
    assert (
        "Offline demo" in offline.info[0].value and "TEST_KEY is not set" in offline.info[0].value
    )
    live = launch(player=Player(**STARTED), backend=live_backend())
    assert not [i for i in live.info if "Offline demo" in i.value]


def test_clicking_a_suggestion_asks_it_and_shows_the_answer_with_its_trace():
    app = click(launch(player=Player(**STARTED)), "What is a stock?")
    assert messages(app) == [
        ("assistant", GREETING),
        ("user", "What is a stock?"),
        ("assistant", "[finance_qa] stub answer for: What is a stock?"),
    ]
    assert "Answered by Finance Q&A. Checked by the Guardian." in [c.value for c in app.caption]
    assert [e.label for e in app.expander] == ["How Penny answered"]
    rows = app.session_state["chat"][0].trace
    assert [r.who for r in rows] == ["Router", "Guardian"]


def test_typing_a_question_works_and_the_conversation_builds_up():
    app = launch(player=Player(**STARTED))
    app.chat_input[0].set_value("why is my paycheck smaller").run()
    app.chat_input[0].set_value("what is a stock").run()
    assert not app.exception
    assert [name for name, _ in messages(app)] == [
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert messages(app)[2][1].startswith("[tax] stub answer")
    assert len(app.session_state["chat"]) == 2


def test_a_real_answer_shows_its_sources_and_the_full_trace():
    backend = live_backend(says("A stock is a small piece of a company."))
    app = launch(player=Player(**STARTED), backend=backend)
    app.chat_input[0].set_value("what is a stock and what are shares").run()
    assert messages(app)[-1] == ("assistant", "A stock is a small piece of a company.")
    assert [e.label for e in app.expander] == ["Sources (1)", "How Penny answered"]
    turn = app.session_state["chat"][0]
    assert turn.citations[0].article_id == "what-is-a-stock"
    assert [r.what for r in turn.trace] == [
        "Sent to Finance Q&A (default)",
        "Searched the articles. Best match: what-is-a-stock",
        "Wrote a draft",
        "Approved",
    ]


def test_money_in_an_answer_is_shown_as_money_not_as_maths():
    plan = ToolCall(id="c1", name="plan_goal", input={"goal_cents": 6000, "weeks": 8})
    backend = live_backend(
        LLMResponse(tool_calls=[plan], stop_reason="tool_use"),
        says("Save $7.50 each week to reach $60.00."),
    )
    app = launch(player=Player(**STARTED), backend=backend)
    click(app, "I want a \\$60 game in 8 weeks. How much per week?")
    _, shown = messages(app)[-1]
    assert shown == "Save \\$7.50 each week to reach \\$60.00."  # dollars escaped for Streamlit
    assert messages(app)[-2][1] == "I want a \\$60 game in 8 weeks. How much per week?"
    assert app.session_state["chat"][0].reply == "Save $7.50 each week to reach $60.00."
    assert any("Answered by Goal and Game Coach" in c.value for c in app.caption)


def test_the_agents_get_the_players_name_and_level():
    backend = live_backend(says("A stock is a small piece of a company."))
    app = launch(player=Player(**STARTED), backend=backend)
    app.chat_input[0].set_value("what is a stock and what are shares").run()
    system = backend.graph.agents["finance_qa"].llm.calls[0]["system"]
    assert "a child called Sam" in system and "correct money terms" in system


def test_restart_clears_the_conversation_and_starts_a_new_session():
    app = click(launch(player=Player(**STARTED)), "What is a stock?")
    first_session = app.session_state["session_id"]
    click(app, "Restart setup")
    assert "chat" not in app.session_state
    click(app, "Skip, start as a Starter")
    assert app.session_state["chat"] == [] and app.session_state["session_id"] != first_session


def test_a_crash_in_the_graph_becomes_a_safe_reply():
    class Broken:
        sink = InMemoryTraceSink()

        def ask(self, *args, **kwargs):
            raise RuntimeError("graph exploded")

    broken = Backend(Broken(), Broken.sink, True, "x")
    turn = ask(broken, Player(**STARTED), "hi", "s")
    assert turn.reply == SAFE_FALLBACK and "RuntimeError" in turn.caption
