import json
from datetime import UTC, date, datetime

import pytest

from penny.agents.grounding import SAMPLE_NOTE
from penny.agents.market_agent import (
    MARKET_UNSURE,
    MarketAgent,
    direction,
    find_ticker,
    market_tools,
    signed_pct,
    size_pct,
)
from penny.contracts import Level, LLMResponse, ToolCall
from penny.graph.build import PennyGraph
from penny.graph.stubs import KeywordRouter, default_agents
from penny.graph.types import AgentRequest, KidContext
from penny.llm.fake import FakeLLM
from penny.market.models import MarketDataError, PriceHistory, Quote
from penny.market.sample import SampleProvider
from penny.observability import InMemoryTraceSink

FRIDAY = date(2026, 10, 16)


class LiveLike:
    """A provider with fixed, non-sample answers."""

    name = "yfinance"

    def quote(self, symbol):
        if symbol.upper() != "DIS":
            raise MarketDataError(f"no provider could answer (yfinance: no prices for {symbol})")
        return Quote(symbol="DIS", name="Walt Disney", price_cents=11059, previous_close_cents=11068,
                     as_of=FRIDAY, source="yfinance", fetched_at=datetime(2026, 10, 16, tzinfo=UTC))  # fmt: skip

    def history(self, symbol, days=30):
        closes = [10000, 10200, 10100, 10500, 11059][-days:]
        return PriceHistory(symbol="DIS", dates=[date(2026, 10, d) for d in range(12, 17)],
                            closes_cents=closes, source="yfinance", fetched_at=datetime(2026, 10, 16, tzinfo=UTC))  # fmt: skip


def tool(name, market=None):
    return next(t for t in market_tools(market or LiveLike()) if t.name == name)


def calls(name, call_id="c1", **arguments):
    return LLMResponse(
        tool_calls=[ToolCall(id=call_id, name=name, input=arguments)], stop_reason="tool_use"
    )


def says(text):
    return LLMResponse(text=text)


def ask(llm, question, market=None, level=Level.STARTER, sink=None):
    agent = MarketAgent(llm, "main-m", market or LiveLike(), sink=sink)
    return agent.respond(
        AgentRequest(trace_id="t1", kid=KidContext(nickname="Sam", level=level), question=question)
    )


# ------------------------------------------------------------------ tools


@pytest.mark.parametrize(
    ("company", "tickers"),
    [
        ("Disney", ["DIS"]),
        ("roblox", ["RBLX"]),
        ("dis", ["DIS"]),
        ("Coca", ["KO"]),
        ("  NINTENDO ", ["NTDOY"]),
    ],
)
def test_find_ticker_matches_names_and_symbols(company, tickers):
    assert [m["ticker"] for m in find_ticker(company)["matches"]] == tickers


def test_find_ticker_says_when_a_company_is_not_in_the_list():
    result = find_ticker("Tesla")
    assert result["matches"] == [] and "Ask the child for the ticker" in result["note"]


def test_get_quote_tool_gives_ready_to_say_facts():
    assert tool("get_quote").fn(ticker="dis") == {
        "company": "Walt Disney",
        "ticker": "DIS",
        "price": "$110.59",
        "previous_close": "$110.68",
        "change_since_previous_close": "-0.08%",
        "direction_since_previous_close": "down",
        "size_of_change": "0.08%",
        "as_of": "2026-10-16",
        "source": "yfinance",
        "data": "live price",
    }


def test_sample_data_is_labelled_in_the_tool_result():
    sample = SampleProvider(today=lambda: FRIDAY)
    facts = tool("get_quote", sample).fn(ticker="DIS")
    assert (facts["source"], facts["data"]) == ("sample", "sample data, not a live price")


def test_get_price_history_tool_summarises_the_moves():
    out = tool("get_price_history").fn(ticker="DIS", days=5)
    assert out["start_price"] == "$100.00" and out["end_price"] == "$110.59"
    assert out["change_over_the_period"] == "+10.59%"
    assert (out["direction_over_the_period"], out["size_of_change"]) == ("up", "10.59%")
    assert (out["highest"], out["lowest"]) == ("$110.59", "$100.00")
    assert out["trading_days"] == 5 and out["from"] == "2026-10-12" and out["to"] == "2026-10-16"
    assert out["typical_daily_move"].endswith("%") and out["data"] == "live price"


def test_history_tool_limits_and_unknown_tickers_raise():
    with pytest.raises(ValueError):
        tool("get_price_history").fn(ticker="DIS", days=200)
    with pytest.raises(MarketDataError, match="no provider could answer"):
        tool("get_quote").fn(ticker="ZZZ")


def test_signed_pct_direction_and_size():
    assert [signed_pct(v) for v in (1.234, -0.08, 0)] == ["+1.23%", "-0.08%", "+0.00%"]
    assert [direction(v) for v in (1.234, -0.08, 0, 0.001, -0.004)] == [
        "up",
        "down",
        "unchanged",
        "unchanged",
        "unchanged",
    ]
    assert [size_pct(v) for v in (1.234, -3.09)] == ["1.23%", "3.09%"]


def test_the_prompt_asks_for_direction_and_size_and_keeps_the_jar_for_saving():
    llm = FakeLLM([says("Which company?")])
    ask(llm, "price")
    system = llm.calls[0]["system"]
    assert 'never "down by -3.09%"' in system and "Do not use it for share prices" in system


# ------------------------------------------------------------------ answering


def test_a_price_question_is_answered_from_the_quote_tool():
    llm = FakeLLM(
        [
            calls("find_ticker", company="Disney"),
            calls("get_quote", "c2", ticker="DIS"),
            says("Disney's price is $110.59, down -0.08% from yesterday."),
        ]
    )
    reply = ask(llm, "how much is a Disney share?")
    assert reply.text == "Disney's price is $110.59, down -0.08% from yesterday."
    lines = reply.evidence.splitlines()
    assert lines[0].startswith("find_ticker(") and lines[1].startswith("get_quote(")
    assert json.loads(lines[1].split(" -> ", 1)[1])["price"] == "$110.59"


def test_a_number_with_no_successful_tool_is_replaced():
    assert ask(FakeLLM([says("Disney is about $100.")]), "disney price").text == MARKET_UNSURE
    failed = FakeLLM([calls("get_quote", ticker="ZZZ"), says("ZZZ costs $5.")])
    assert ask(failed, "price of ZZZ").text == MARKET_UNSURE
    assert "no provider could answer" in failed.calls[1]["messages"][-1].content


def test_sample_data_must_be_mentioned_and_is_added_if_the_model_forgets():
    sample = SampleProvider(today=lambda: FRIDAY)
    forgot = ask(
        FakeLLM(
            [
                calls("get_quote", ticker="DIS"),
                says("Disney costs a little over a hundred dollars."),
            ]
        ),
        "disney price",
        market=sample,
    )
    assert forgot.text.endswith(SAMPLE_NOTE)
    said_it = ask(
        FakeLLM(
            [calls("get_quote", ticker="DIS"), says("This is sample data, but here is the idea.")]
        ),
        "disney price",
        market=sample,
    )
    assert said_it.text == "This is sample data, but here is the idea."
    live = ask(
        FakeLLM([calls("get_quote", ticker="DIS"), says("Disney is $110.59.")]), "disney price"
    )
    assert SAMPLE_NOTE not in live.text


def test_the_fixed_question_never_gets_the_sample_note():
    sample = SampleProvider(today=lambda: FRIDAY)
    reply = ask(FakeLLM([says("Which company? Maybe one costs $10.")]), "price", market=sample)
    assert reply.text == MARKET_UNSURE


def test_the_prompt_forbids_advice_and_predictions_and_sets_the_level():
    llm = FakeLLM([says("Which company do you mean?")])
    ask(llm, "should I buy Roblox", level=Level.SAVER)
    system = llm.calls[0]["system"]
    for phrase in (
        "Never say whether to buy or sell",
        "never guess where a price will go",
        "sample data",
        "3 to 5 short sentences",
        "a child called Sam",
    ):
        assert phrase in system
    assert [t.name for t in llm.calls[0]["tools"]] == [
        "find_ticker",
        "get_quote",
        "get_price_history",
    ]


def test_tool_calls_are_traced_under_the_market_agent():
    sink = InMemoryTraceSink()
    ask(
        FakeLLM([calls("get_quote", ticker="DIS"), says("Disney is $110.59.")]),
        "disney price",
        sink=sink,
    )
    assert [(e.agent, e.kind, e.name) for e in sink.for_trace("t1")] == [
        ("market", "llm", "main-m"),
        ("market", "tool", "get_quote"),
        ("market", "llm", "main-m"),
    ]


# ------------------------------------------------------------------ routing and the graph


@pytest.mark.parametrize(
    "question",
    [
        "What's Roblox's price?",
        "how much is disney right now",
        "Nintendo stock price",
        "quote for KO",
        "what is the share price of Sony",
    ],
)
def test_questions_about_companies_children_know_go_to_the_market_agent(question):
    assert KeywordRouter().route(question, [], KidContext()).agent == "market"


def test_in_the_graph_a_price_question_is_answered_and_checked():
    llm = FakeLLM(
        [calls("get_quote", ticker="RBLX"), says("Roblox is $49.55 in this practice data.")]
    )
    sample = SampleProvider(today=lambda: FRIDAY)
    graph = PennyGraph(agents={**default_agents(), "market": MarketAgent(llm, "main-m", sample)})
    result = graph.ask("What's Roblox's price?", session_id="s")
    assert (result.route, result.approved) == ("market", True)
    assert result.reply.endswith(SAMPLE_NOTE)
