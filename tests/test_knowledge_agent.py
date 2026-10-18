import pytest

from kb_helpers import corpus
from penny.agents.knowledge import (
    MAX_CITATIONS,
    NOT_SURE,
    OLDER_READER_NOTE,
    KnowledgeAgent,
    is_small_talk,
)
from penny.agents.loop import AgentError
from penny.contracts import Level, LLMResponse, Message, ToolCall
from penny.graph.build import PennyGraph
from penny.graph.stubs import default_agents
from penny.graph.types import AgentRequest, KidContext
from penny.kb.embedding import HashingEmbedder
from penny.kb.index import KBIndex
from penny.llm.errors import LLMError
from penny.llm.fake import FakeLLM
from penny.observability import InMemoryTraceSink

INDEX = KBIndex.build(corpus(draft_bond=False), HashingEmbedder())  # all four reviewed


def says(text: str) -> LLMResponse:
    return LLMResponse(text=text)


def searches(query: str, call_id: str = "c1") -> LLMResponse:
    call = ToolCall(id=call_id, name="search_articles", input={"query": query})
    return LLMResponse(tool_calls=[call], stop_reason="tool_use")


def ask(llm, question, *, level=Level.BUILDER, history=None, feedback=None, sink=None, **kwargs):
    agent = KnowledgeAgent(llm, "main-model", INDEX, sink=sink, **kwargs)
    request = AgentRequest(
        trace_id="t1",
        kid=KidContext(nickname="Sam", level=level),
        question=question,
        history=history or [],
        feedback=feedback or [],
    )
    return agent.respond(request)


# ------------------------------------------------------------------ grounded answers


def test_a_covered_question_is_answered_from_the_passages_with_citations():
    llm = FakeLLM([says("A stock is a small piece of a company.  ")])
    reply = ask(llm, "what is a stock and what are shares")

    assert reply.text == "A stock is a small piece of a company."
    assert reply.citations[0].article_id == "what-is-a-stock"
    assert reply.citations[0].sources[0].url == "https://example.gov/what-is-a-stock"

    sent = llm.calls[0]
    assert sent["model"] == "main-model"
    prompt = sent["messages"][-1].content
    assert prompt.startswith("Question: what is a stock and what are shares")
    assert "[what-is-a-stock]" in prompt and "ownership in a company" in prompt
    assert [t.name for t in sent["tools"]] == ["search_articles"]


def test_citations_are_unique_best_first_and_capped():
    reply = ask(FakeLLM([says("Money things.")]), "money company tax bank loan stock piggy")
    ids = [c.article_id for c in reply.citations]
    assert len(ids) == len(set(ids)) and 1 <= len(ids) <= MAX_CITATIONS


# ------------------------------------------------------------------ "I don't know" is enforced


def test_an_uncovered_question_gets_the_fixed_not_sure_reply_whatever_the_model_says():
    llm = FakeLLM([says("The capital of France is Paris.")])
    reply = ask(llm, "what is the capital of France")
    assert reply.text == NOT_SURE and reply.citations == []
    assert "(no matching articles)" in llm.calls[0]["messages"][-1].content


def test_a_search_that_finds_nothing_still_ends_in_not_sure():
    llm = FakeLLM([searches("quantum chromodynamics"), says("Quarks are tiny particles.")])
    reply = ask(llm, "tell me about quarks")
    assert reply.text == NOT_SURE
    assert "No articles matched" in llm.calls[1]["messages"][-1].content


def test_a_follow_up_can_be_rescued_by_the_models_own_search():
    history = [
        Message.user("what is a stock"),
        Message(role="assistant", content="A stock is a small piece of a company."),
    ]
    llm = FakeLLM(
        [searches("stock shares dividends shareholders"), says("Some companies pay dividends.")]
    )
    reply = ask(llm, "tell me more", history=history)

    assert reply.text == "Some companies pay dividends."
    assert reply.citations[0].article_id == "what-is-a-stock"
    first = llm.calls[0]["messages"]
    assert [(m.role, m.content) for m in first[:2]] == [
        ("user", "what is a stock"),
        ("assistant", "A stock is a small piece of a company."),
    ]
    assert "(no matching articles)" in first[-1].content  # "tell me more" alone found nothing
    assert "[what-is-a-stock]" in llm.calls[1]["messages"][-1].content


def test_the_model_gets_at_most_two_searches():
    llm = FakeLLM(
        [
            searches("zzz qqq", "c1"),
            searches("xxx yyy", "c2"),
            searches("what is a stock", "c3"),
            says("answer"),
        ]
    )
    reply = ask(llm, "tell me more")
    assert "Search limit reached" in llm.calls[3]["messages"][-1].content
    assert reply.text == NOT_SURE  # the third search never ran, so nothing was found


def test_an_empty_search_query_is_rejected_by_validation_not_run():
    llm = FakeLLM([searches(""), says("answer")])
    ask(llm, "tell me more")
    result = llm.calls[1]["messages"][-1]
    assert result.is_error and result.content.startswith("Invalid arguments: query")


# ------------------------------------------------------------------ the reader's level


def test_articles_at_the_readers_level_are_preferred():
    llm = FakeLLM([says("A piggy bank keeps money safe.")])
    reply = ask(llm, "how does saving money in a piggy bank help", level=Level.STARTER)
    prompt = llm.calls[0]["messages"][-1].content
    assert reply.citations[0].article_id == "piggy-bank-basics"
    assert OLDER_READER_NOTE not in prompt


def test_a_harder_article_is_used_when_nothing_at_their_level_matches():
    question = "a bond is a loan that pays interest until maturity"
    starter_llm = FakeLLM([says("A bond is like lending money.")])
    starter = ask(starter_llm, question, level=Level.STARTER)
    prompt = starter_llm.calls[0]["messages"][-1].content
    assert starter.citations[0].article_id == "what-is-a-bond"
    assert OLDER_READER_NOTE in prompt  # the model is told to simplify

    builder_llm = FakeLLM([says("A bond is a loan.")])
    builder = ask(builder_llm, question, level=Level.BUILDER)
    assert builder.citations[0].article_id == "what-is-a-bond"
    assert OLDER_READER_NOTE not in builder_llm.calls[0]["messages"][-1].content


def test_a_harder_article_that_matches_much_better_beats_a_weak_one_at_their_level():
    # piggy-bank-basics (starter) matches "company" weakly; what-is-a-stock (saver) is the answer
    question = "what is a stock share shareholder ownership in a company"
    sink = InMemoryTraceSink()
    llm = FakeLLM([says("A stock is a small piece of a company.")])
    reply = ask(llm, question, level=Level.STARTER, sink=sink)
    assert reply.citations[0].article_id == "what-is-a-stock"
    assert OLDER_READER_NOTE in llm.calls[0]["messages"][-1].content
    assert sink.for_trace("t1")[0].output["above_level"] is True


def test_a_close_match_at_their_level_still_wins(monkeypatch):
    import penny.agents.knowledge as knowledge

    monkeypatch.setattr(knowledge, "LEVEL_SCORE_RATIO", 0.0)  # any match at their level is close
    llm = FakeLLM([says("A stock is a small piece of a company.")])
    reply = ask(llm, "what is a stock share shareholder ownership taxes", level=Level.STARTER)
    assert reply.citations[0].article_id in {"what-are-taxes", "piggy-bank-basics"}
    assert OLDER_READER_NOTE not in llm.calls[0]["messages"][-1].content


def test_the_models_own_search_follows_the_same_level_rule():
    llm = FakeLLM([searches("bond loan interest maturity"), says("A bond is like lending.")])
    reply = ask(llm, "tell me more", level=Level.STARTER)
    result = llm.calls[1]["messages"][-1].content
    assert result.startswith(OLDER_READER_NOTE) and "[what-is-a-bond]" in result
    assert reply.citations[0].article_id == "what-is-a-bond"


@pytest.mark.parametrize(
    ("level", "fragment"),
    [
        (Level.STARTER, "2 to 4 short sentences"),
        (Level.SAVER, "3 to 5 short sentences"),
        (Level.BUILDER, "correct money terms"),
    ],
)
def test_the_prompt_sets_the_reading_level(level, fragment):
    llm = FakeLLM([says("ok")])
    ask(llm, "what is a stock", level=level)
    assert fragment in llm.calls[0]["system"]


# ------------------------------------------------------------------ prompt contents


def test_the_prompt_carries_pennys_values_the_rules_and_the_childs_name():
    llm = FakeLLM([says("ok")])
    ask(llm, "what is a stock")
    system = llm.calls[0]["system"]
    assert "a child called Sam" in system
    assert "Penny's values" in system and "Little drops" in system
    assert "Answer ONLY from the article passages" in system
    assert "Never tell the child what to buy" in system
    assert "safety reviewer" not in system


def test_guardian_feedback_is_added_to_the_prompt_on_a_rewrite():
    llm = FakeLLM([says("ok")])
    ask(llm, "what is a stock", feedback=["remove advice wording: 'you should buy'", "shorter"])
    system = llm.calls[0]["system"]
    assert "not accepted by the safety reviewer" in system
    assert "- remove advice wording: 'you should buy'\n- shorter" in system


def test_only_the_recent_text_turns_of_history_are_sent():
    history = []
    for n in range(5):
        history += [Message.user(f"q{n}"), Message(role="assistant", content=f"a{n}")]
    history.append(Message.tool_result("x", "tool noise"))
    llm = FakeLLM([says("ok")])
    ask(llm, "what is a stock", history=history)
    sent = llm.calls[0]["messages"]
    assert all(m.role in ("user", "assistant") for m in sent)
    assert "tool noise" not in [m.content for m in sent]
    assert len(sent) <= 7 and sent[-1].content.startswith("Question:")
    assert sent[0].content == "a2"  # the last six history entries, minus the tool message


# ------------------------------------------------------------------ small talk


@pytest.mark.parametrize("text", ["hi", "Hello Penny!", "thanks", "thank you so much", "bye"])
def test_greetings_and_thanks_count_as_small_talk(text):
    assert is_small_talk(text) is True


@pytest.mark.parametrize(
    "text",
    ["what is a stock", "hi what is the capital of France", "history of money", "", "okra soup?"],
)
def test_real_questions_do_not(text):
    assert is_small_talk(text) is False


def test_a_greeting_gets_the_models_friendly_reply_without_sources():
    reply = ask(FakeLLM([says("Hi Sam! What money question do you have today?")]), "Hello Penny!")
    assert reply.text.startswith("Hi Sam!") and reply.citations == []


# ------------------------------------------------------------------ failures and tracing


def test_provider_and_loop_failures_pass_through_for_the_graph_to_handle():
    class Down:
        def complete(self, **kwargs):
            raise LLMError("rate limited", retryable=True)

    with pytest.raises(LLMError):
        ask(Down(), "what is a stock")
    with pytest.raises(AgentError, match="cut off"):
        ask(FakeLLM([LLMResponse(text="A sto", stop_reason="max_tokens")]), "what is a stock")


def test_retrievals_model_calls_and_tool_calls_are_all_traced():
    sink = InMemoryTraceSink()
    llm = FakeLLM([searches("stock shares dividends"), says("answer")])
    ask(llm, "tell me more", sink=sink)
    events = sink.for_trace("t1")
    assert [(e.agent, e.kind) for e in events] == [
        ("finance_qa", "retrieval"),  # the code's own first search
        ("finance_qa", "llm"),
        ("finance_qa", "retrieval"),  # the model's search
        ("finance_qa", "tool"),
        ("finance_qa", "llm"),
    ]
    assert events[0].input == {"query": "tell me more", "max_level": "builder"}
    assert events[0].output["confident"] is False
    assert events[0].output["above_level"] is False
    assert events[2].output["confident"] is True
    assert events[2].output["articles"][0] == "what-is-a-stock"


def test_the_agent_name_and_role_are_configurable_for_reuse():
    sink = InMemoryTraceSink()
    llm = FakeLLM([says("ok")])
    ask(llm, "what are taxes", sink=sink, name="tax", role="You explain taxes. Never give advice.")
    assert "You explain taxes. Never give advice." in llm.calls[0]["system"]
    assert {e.agent for e in sink.events} == {"tax"}


# ------------------------------------------------------------------ inside the graph


def graph_with(llm, sink=None):
    agent = KnowledgeAgent(llm, "main-model", INDEX, sink=sink)
    return PennyGraph(agents={**default_agents(), "finance_qa": agent}, sink=sink)


def test_in_the_graph_an_answer_comes_back_approved_with_its_sources():
    result = graph_with(FakeLLM([says("A stock is a small piece of a company.")])).ask(
        "what is a stock", session_id="s", kid=KidContext(level=Level.SAVER)
    )
    assert (result.route, result.approved, result.rewrites) == ("finance_qa", True, 0)
    assert result.citations[0].article_id == "what-is-a-stock"


def test_in_the_graph_advice_wording_is_rejected_and_rewritten():
    llm = FakeLLM([says("You should buy this stock now."), says("A stock is a small piece.")])
    result = graph_with(llm).ask("what is a stock", session_id="s")
    assert result.reply == "A stock is a small piece." and result.rewrites == 1
    assert "you should buy" in llm.calls[1]["system"]


def test_in_the_graph_the_not_sure_reply_passes_the_guardian():
    result = graph_with(FakeLLM([says("Paris.")])).ask("capital of France", session_id="s")
    assert result.reply == NOT_SURE and result.approved is True and result.citations == []


def test_in_the_graph_a_provider_outage_ends_in_the_safe_fallback():
    class Down:
        def complete(self, **kwargs):
            raise LLMError("down", retryable=True)

    result = graph_with(Down()).ask("what is a stock", session_id="s")
    assert result.fallback_used is True and "LLMError: down" in result.last_issues[0]


def test_in_the_graph_the_second_turn_sees_the_first():
    llm = FakeLLM([says("A stock is a small piece."), says("Yes, some pay dividends.")])
    graph = graph_with(llm)
    graph.ask("what is a stock", session_id="s")
    graph.ask("do shareholders get dividends", session_id="s")
    second = llm.calls[1]["messages"]
    assert [(m.role, m.content) for m in second[:2]] == [
        ("user", "what is a stock"),
        ("assistant", "A stock is a small piece."),
    ]


# ------------------------------------------------------------------ closing note (used by Tax)


def test_a_closing_note_is_added_in_code_when_the_model_leaves_it_out():
    llm = FakeLLM([says("Taxes pay for shared things like roads.")])
    reply = ask(
        llm, "what are taxes used for", closing_note="This is for learning, not tax advice."
    )
    assert (
        reply.text
        == "Taxes pay for shared things like roads. This is for learning, not tax advice."
    )


def test_a_closing_note_is_not_repeated_if_the_model_already_said_it():
    text = "Taxes pay for roads. This is for learning, NOT TAX ADVICE."
    reply = ask(FakeLLM([says(text)]), "what are taxes used for", closing_note="not tax advice.")
    assert reply.text == text


def test_the_closing_note_is_not_added_to_not_sure_or_small_talk():
    note = "This is for learning, not tax advice."
    not_sure = ask(FakeLLM([says("Paris.")]), "capital of France", closing_note=note)
    assert not_sure.text == NOT_SURE
    greeting = ask(FakeLLM([says("Hi Sam!")]), "hello", closing_note=note)
    assert greeting.text == "Hi Sam!"


def test_only_articles_that_matched_nearly_as_well_as_the_best_are_cited():
    from penny.agents.knowledge import CITATION_SCORE_RATIO
    from penny.kb.retriever import retrieve

    question = "why is tax taken from my paycheck and what is income tax"
    found = retrieve(INDEX, question)
    best_by_article: dict[str, float] = {}
    for hit in found.hits:
        best_by_article.setdefault(hit.chunk.article_id, hit.score)
    top = max(best_by_article.values())
    expected = [a for a, s in best_by_article.items() if s >= top * CITATION_SCORE_RATIO]

    reply = ask(FakeLLM([says("Tax is taken from your pay.")]), question)
    assert [c.article_id for c in reply.citations] == expected[:MAX_CITATIONS]
    assert reply.citations[0].article_id == "what-are-taxes"
