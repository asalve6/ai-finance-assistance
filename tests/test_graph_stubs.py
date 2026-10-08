import pytest

from penny.contracts import Verdict
from penny.graph.stubs import (
    SAFE_FALLBACK,
    KeywordRouter,
    RuleGuardian,
    StubSpecialist,
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
