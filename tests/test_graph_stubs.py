import pytest

from penny.contracts import Level, Verdict
from penny.graph.stubs import (
    MAX_SENTENCES,
    SAFE_FALLBACK,
    KeywordRouter,
    RuleGuardian,
    StubSpecialist,
    count_sentences,
    default_agents,
)
from penny.graph.types import SPECIALISTS, AgentReply, AgentRequest, KidContext


def request(question="hi", feedback=None):
    return AgentRequest(trace_id="t", kid=KidContext(), question=question, feedback=feedback or [])


@pytest.mark.parametrize(
    ("question", "agent"),
    [
        ("Why is my first paycheck smaller than I expected?", "tax"),
        ("what is a Roth IRA", "tax"),
        ("how do I diversify my portfolio", "portfolio"),
        ("what is the stock price of Nintendo", "market"),
        ("how much is Disney trading at", "market"),
        ("how much do I save per week for a bike", "coach"),
        ("how do I win at the lemonade game", "coach"),
        ("what is a stock?", "finance_qa"),
        ("what is compound interest", "finance_qa"),
        ("", "finance_qa"),
    ],
)
def test_keyword_router_picks_the_expected_specialist(question, agent):
    decision = KeywordRouter().route(question, [], KidContext())
    assert decision.agent == agent
    assert decision.reason


def test_the_router_explains_which_keyword_matched():
    assert KeywordRouter().route("my paycheck", [], KidContext()).reason == "matched 'paycheck'"
    assert KeywordRouter().route("hello", [], KidContext()).reason == "default"


def test_there_is_one_stub_for_each_specialist_and_it_echoes_feedback():
    agents = default_agents()
    assert tuple(agents) == SPECIALISTS
    plain = StubSpecialist("tax").respond(request("why tax?"))
    assert plain.text == "[tax] stub answer for: why tax?"
    revised = StubSpecialist("tax").respond(request("why tax?", ["be kinder", "shorter"]))
    assert "(revising: be kinder; shorter)" in revised.text


@pytest.mark.parametrize("text", ["", "   \n"])
def test_the_rule_guardian_rejects_empty_replies(text):
    verdict = RuleGuardian().review(request(), AgentReply(text=text))
    assert verdict == Verdict(approved=False, reasons=["the reply was empty"])


def test_the_rule_guardian_rejects_advice_and_promises_with_one_reason_each():
    reply = AgentReply(text="You SHOULD BUY this, it is guaranteed to win.")
    verdict = RuleGuardian().review(request(), reply)
    assert verdict.approved is False
    assert len(verdict.reasons) == 2
    assert any("you should buy" in r for r in verdict.reasons)
    assert any("guaranteed" in r for r in verdict.reasons)


def test_the_rule_guardian_approves_clean_replies():
    reply = AgentReply(text="A stock is a small piece of a company. This is for learning.")
    assert RuleGuardian().review(request(), reply).approved is True


def test_the_fallback_is_kind_and_short():
    assert "grown-up" in SAFE_FALLBACK and len(SAFE_FALLBACK.split()) < 40


# ------------------------------------------------------------------ format rules


def level_request(level):
    return AgentRequest(trace_id="t", kid=KidContext(level=level), question="q")


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("One. Two! Three?", 3),
        ("It costs $7.50 each week. That is all.", 2),
        ("No ending punctuation", 1),
        ("  Spaces around.   Second one.  ", 2),
        ("", 0),
    ],
)
def test_count_sentences(text, count):
    assert count_sentences(text) == count


@pytest.mark.parametrize(
    ("level", "limit"), [(Level.STARTER, 5), (Level.SAVER, 6), (Level.BUILDER, 8)]
)
def test_replies_longer_than_the_readers_limit_are_rejected(level, limit):
    assert MAX_SENTENCES[level] == limit
    at_limit = AgentReply(text=" ".join(["A short one."] * limit))
    over = AgentReply(text=" ".join(["A short one."] * (limit + 1)))
    assert RuleGuardian().review(level_request(level), at_limit).approved is True
    verdict = RuleGuardian().review(level_request(level), over)
    assert verdict.reasons == [f"too long: {limit + 1} sentences, the limit is {limit}"]


@pytest.mark.parametrize(
    "text",
    [
        "Two ways:\n- the price goes up\n- dividends",
        "Steps:\n1. Save.\n2. Wait.",
        "# Stocks\nA stock is a slice.",
        "A **dividend** is a payment.",
        "* one thing",
    ],
)
def test_lists_headings_and_bold_are_rejected(text):
    verdict = RuleGuardian().review(level_request(Level.BUILDER), AgentReply(text=text))
    assert verdict.reasons == ["write plain sentences: no lists, headings or bold"]


def test_plain_text_with_a_dash_or_a_number_inside_a_sentence_is_fine():
    reply = AgentReply(text="Save a little - even 1 dollar - each week. In 4 weeks it adds up.")
    assert RuleGuardian().review(level_request(Level.STARTER), reply).approved is True


def test_every_problem_is_reported_at_once_so_one_rewrite_can_fix_them_all():
    text = "- You should buy it.\n" + " ".join(["More words here."] * 9)
    verdict = RuleGuardian().review(level_request(Level.STARTER), AgentReply(text=text))
    assert len(verdict.reasons) == 3


def test_a_phrase_from_the_childs_own_question_may_be_echoed_back():
    reply = AgentReply(text="Nobody can promise you will get rich. Prices can go up or down.")
    asked = AgentRequest(trace_id="t", kid=KidContext(), question="Can I GET RICH with stocks?")
    assert RuleGuardian().review(asked, reply).approved is True
    not_asked = AgentRequest(trace_id="t", kid=KidContext(), question="what is a stock")
    assert RuleGuardian().review(not_asked, reply).approved is False
