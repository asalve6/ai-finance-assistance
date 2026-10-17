import json
from datetime import UTC, date, datetime

import pytest

from penny.agents.grounding import SAMPLE_NOTE
from penny.agents.guardian import TRUSTED_REPLIES
from penny.agents.portfolio_agent import (
    NO_PORTFOLIO,
    PORTFOLIO_UNSURE,
    PortfolioAgent,
    changed,
    portfolio_tools,
    summarise,
)
from penny.contracts import Level, LLMResponse, ToolCall
from penny.graph.build import PennyGraph
from penny.graph.stubs import KeywordRouter, default_agents
from penny.graph.types import AgentRequest, KidContext
from penny.llm.fake import FakeLLM
from penny.market.models import MarketDataError, PriceHistory, Quote
from penny.market.sample import SampleProvider
from penny.observability import InMemoryTraceSink
from penny.ui.session import Player

FRIDAY = date(2026, 10, 16)
PRICES = {"DIS": 11000, "KO": 6000, "RBLX": 5000}
HISTORY = {
    "DIS": [10000, 10100, 10000, 10100, 10000],  # about 1% moves
    "KO": [6000, 6001, 6000, 6001, 6000],  # tiny moves
}


class Market:
    name = "yfinance"

    def __init__(self):
        self.calls = []

    def quote(self, symbol):
        self.calls.append(("quote", symbol))
        if symbol not in PRICES:
            raise MarketDataError(f"no provider could answer ({symbol})")
        return Quote(symbol=symbol, name={"DIS": "Walt Disney", "KO": "Coca-Cola", "RBLX": "Roblox"}[symbol],
                     price_cents=PRICES[symbol], previous_close_cents=PRICES[symbol], as_of=FRIDAY,
                     source="yfinance", fetched_at=datetime(2026, 10, 16, tzinfo=UTC))  # fmt: skip

    def history(self, symbol, days=30):
        self.calls.append(("history", symbol, days))
        if symbol not in HISTORY:
            raise MarketDataError("no history")
        return PriceHistory(symbol=symbol, dates=[FRIDAY] * 5, closes_cents=HISTORY[symbol],
                            source="yfinance", fetched_at=datetime(2026, 10, 16, tzinfo=UTC))  # fmt: skip


def says(text):
    return LLMResponse(text=text)


def calls(name, call_id="c1", **arguments):
    return LLMResponse(
        tool_calls=[ToolCall(id=call_id, name=name, input=arguments)], stop_reason="tool_use"
    )


def ask(llm, question, holdings, market=None, sink=None):
    agent = PortfolioAgent(llm, "main-m", market or Market(), sink=sink)
    kid = KidContext(nickname="Sam", level=Level.SAVER, practice_holdings=holdings)
    return agent.respond(AgentRequest(trace_id="t1", kid=kid, question=question))


# ------------------------------------------------------------------ the summary


def test_the_summary_prices_the_holdings_and_explains_spread_and_bumpiness():
    out = summarise({"DIS": 3, "KO": 1}, Market())
    assert out["total_value"] == "$390.00"
    assert [(h["ticker"], h["value"], h["share_of_portfolio"]) for h in out["holdings"]] == [
        ("DIS", "$330.00", "85%"),
        ("KO", "$60.00", "15%"),
    ]
    assert out["spread"] == "mostly in one company" and "one company" in out["spread_means"]
    assert out["effective_number_of_companies"] == "1.4"  # 1 / (0.846² + 0.154²) = 1.35
    # Disney moves about 1.15% a day, Coca-Cola about 0.02%; weighted 85/15 that is about 0.98%
    assert (out["bumpiness"], out["typical_daily_move"]) == ("Calmer", "0.98%")
    assert (out["source"], out["data"]) == ("yfinance", "live prices")


def test_missing_history_makes_bumpiness_unknown_but_the_rest_works():
    out = summarise({"RBLX": 2}, Market())
    assert out["total_value"] == "$100.00" and out["bumpiness"] == "Unknown"
    assert out["bumpiness_means"] == "There is not enough price history to tell."


def test_a_price_that_cannot_be_found_fails_the_summary():
    with pytest.raises(MarketDataError):
        summarise({"ZZZ": 1}, Market())


def test_sample_prices_are_labelled():
    out = summarise({"DIS": 1, "KO": 1}, SampleProvider(today=lambda: FRIDAY))
    assert (out["source"], out["data"]) == ("sample", "sample data, not live prices")


# ------------------------------------------------------------------ what-if changes


@pytest.mark.parametrize(
    ("change", "result"),
    [
        (("KO", 2), {"DIS": 3, "KO": 3}),
        (("rblx", 4), {"DIS": 3, "KO": 1, "RBLX": 4}),
        (("DIS", -1), {"DIS": 2, "KO": 1}),
        (("KO", -1), {"DIS": 3}),
    ],
)
def test_changed_adds_removes_and_drops_companies(change, result):
    assert changed({"DIS": 3, "KO": 1}, *change) == result


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("KO", 0), "cannot be zero"),
        (("KO", -2), "only have 1 practice shares of KO"),
        (("NKE", -1), "only have 0"),
        (("not a ticker", 1), "does not look like"),
    ],
)
def test_impossible_changes_are_refused(change, message):
    with pytest.raises((ValueError, MarketDataError), match=message):
        changed({"DIS": 3, "KO": 1}, *change)


def test_a_change_cannot_empty_the_portfolio():
    with pytest.raises(ValueError, match="empty"):
        changed({"KO": 1}, "KO", -1)


def test_try_a_change_shows_before_and_after_without_touching_the_real_holdings():
    # Two companies always leave one with half or more, so spreading needs a third company.
    holdings = {"DIS": 1, "KO": 1}  # $110 and $60: Disney is 65%
    tool = next(t for t in portfolio_tools(holdings, Market()) if t.name == "try_a_change")
    out = tool.fn(ticker="rblx", shares_change=2)  # adds $100 of Roblox: Disney becomes 41%
    assert out["change"] == "add 2 practice shares of RBLX"
    assert out["before"]["spread"] == "mostly in one company"
    assert out["after"]["spread"] == "somewhat spread out"
    assert out["after"]["holdings"][0]["share_of_portfolio"] == "41%"
    assert out["note"] == "Practice only. Nothing is really bought or sold."
    assert holdings == {"DIS": 1, "KO": 1}


def test_two_companies_are_always_concentrated():
    out = summarise({"DIS": 1, "KO": 2}, Market())  # $110 and $120
    assert out["spread"] == "mostly in one company"


def test_tool_arguments_are_validated():
    tool = next(t for t in portfolio_tools({"DIS": 1}, Market()) if t.name == "try_a_change")
    for bad in ({"ticker": "KO", "shares_change": 500}, {"ticker": "", "shares_change": 1}):
        with pytest.raises(ValueError):
            tool.fn(**bad)


# ------------------------------------------------------------------ answering


def test_an_empty_portfolio_gets_a_fixed_reply_without_a_model_call():
    llm = FakeLLM([])
    assert ask(llm, "is my portfolio spread out?", {}).text == NO_PORTFOLIO
    assert llm.calls == []


def test_a_spread_question_is_answered_from_the_analysis():
    llm = FakeLLM(
        [
            calls("analyze_my_portfolio"),
            says("Your practice portfolio is worth $390.00 and is concentrated."),
        ]
    )
    reply = ask(llm, "is my portfolio spread out?", {"DIS": 3, "KO": 1})
    assert reply.text == "Your practice portfolio is worth $390.00 and is concentrated."
    assert reply.evidence.startswith("analyze_my_portfolio({}) -> ")
    assert json.loads(reply.evidence.split(" -> ", 1)[1])["total_value"] == "$390.00"


def test_a_number_with_no_tool_behind_it_is_replaced():
    reply = ask(FakeLLM([says("It is worth about $400.")]), "how much is it worth", {"DIS": 3})
    assert reply.text == PORTFOLIO_UNSURE


def test_sample_prices_must_be_disclosed():
    llm = FakeLLM([calls("analyze_my_portfolio"), says("Your portfolio is concentrated.")])
    reply = ask(
        llm,
        "how spread out is it",
        {"DIS": 3, "KO": 1},
        market=SampleProvider(today=lambda: FRIDAY),
    )
    assert reply.text.endswith(SAMPLE_NOTE)


def test_the_prompt_is_practice_only_and_names_both_tools():
    llm = FakeLLM([says("What would you like to know about it?")])
    ask(llm, "tell me about my portfolio", {"DIS": 1})
    call = llm.calls[0]
    assert "do not tell the child what to change, add, buy or sell" in call["system"]
    assert "one company's bad day" in call["system"] and "practice money only" in call["system"]
    assert [t.name for t in call["tools"]] == ["analyze_my_portfolio", "try_a_change"]


def test_the_fixed_replies_are_trusted_and_have_no_numbers():
    for text in (NO_PORTFOLIO, PORTFOLIO_UNSURE):
        assert text in TRUSTED_REPLIES and not any(ch.isdigit() for ch in text)


def test_tool_calls_are_traced_under_the_portfolio_agent():
    sink = InMemoryTraceSink()
    ask(
        FakeLLM([calls("analyze_my_portfolio"), says("It is concentrated.")]),
        "spread?",
        {"DIS": 3},
        sink=sink,
    )
    assert [(e.agent, e.kind) for e in sink.for_trace("t1")] == [
        ("portfolio", "llm"),
        ("portfolio", "tool"),
        ("portfolio", "llm"),
    ]


# ------------------------------------------------------------------ the player, routing and the graph


def test_the_players_practice_holdings_reach_the_agents():
    player = Player(practice_holdings={"DIS": 2})
    kid = player.kid()
    assert kid.practice_holdings == {"DIS": 2}
    kid.practice_holdings["KO"] = 1
    assert player.practice_holdings == {"DIS": 2}  # a copy, so agents cannot change the player


@pytest.mark.parametrize(
    "question", ["is my portfolio spread out?", "how do I diversify", "what are my holdings worth"]
)
def test_portfolio_questions_are_routed_to_the_portfolio_agent(question):
    assert KeywordRouter().route(question, [], KidContext()).agent == "portfolio"


def test_in_the_graph_the_holdings_survive_the_checkpoint_and_reach_the_agent():
    llm = FakeLLM([calls("analyze_my_portfolio"), says("It is concentrated.")])
    graph = PennyGraph(agents={**default_agents(), "portfolio": PortfolioAgent(llm, "m", Market())})
    kid = KidContext(practice_holdings={"DIS": 3, "KO": 1})
    result = graph.ask("is my portfolio spread out?", session_id="s", kid=kid)
    assert (result.route, result.reply, result.approved) == (
        "portfolio",
        "It is concentrated.",
        True,
    )
