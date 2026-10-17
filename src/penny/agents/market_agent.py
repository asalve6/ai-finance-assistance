"""The Market Analysis agent: today's price of a company a child knows, and what it means.

Every price and percentage comes from a tool backed by the market chain (Yahoo Finance, then
Alpha Vantage, then sample data, behind a 30-minute cache). Two rules are enforced in code:

- a number with no successful tool behind it replaces the reply with a fixed question;
- if any price came from sample data, the reply must say so, and a note is added if it does not.

The agent explains; it never predicts a price or says whether to buy.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from penny.agents.grounding import successful_runs, tool_backed_reply
from penny.agents.loop import run_agent
from penny.agents.prompts import recent_history, system_prompt
from penny.agents.tools import make_tool
from penny.contracts import LLMClient, Message, ToolSpec, TraceSink
from penny.engines.portfolio import daily_move_pct
from penny.graph.types import AgentReply, AgentRequest
from penny.market.models import WATCHLIST, Quote
from penny.market.provider import MarketProvider
from penny.money import dollars
from penny.observability import NullTraceSink

MARKET_ROLE = (
    "You help children read stock prices: what a price is, how it changed, and what that does "
    "and does not mean."
)

MARKET_UNSURE = (
    "I can look that up for you. Which company do you mean? You can tell me its name, like "
    "Disney or Roblox."
)

SAMPLE_NOTE = "These prices are sample data for practice, not live prices."

_RULES = """\
How to answer:
- Never state a price, a change or a percentage yourself. Use get_quote for the latest price and
  get_price_history for how it moved. If you only know the company's name, call find_ticker first.
- Say amounts exactly the way the tool wrote them, for example "$110.59". Say a change with its
  direction and size, for example "down 3.09%", never "down by -3.09%". Give each number once.
- Keep the jar and drops comparison for saving questions. Do not use it for share prices.
- Explain what the numbers mean in plain words. One day's move does not tell you much. Prices go
  up and down, and nobody knows what comes next.
- Never say whether to buy or sell, and never guess where a price will go.
- If a tool says the data is sample data, say so in your answer.
- If the company is not found, ask for its name or its ticker symbol.
- Write plain sentences and stay inside the sentence limit below. No lists, headings or bold."""


def signed_pct(value: float) -> str:
    return f"{value:+.2f}%"


def direction(value: float) -> str:
    """'up', 'down' or 'unchanged', so the model never has to say "down by -3%"."""
    if round(value, 2) == 0:
        return "unchanged"
    return "up" if value > 0 else "down"


def size_pct(value: float) -> str:
    return f"{abs(value):.2f}%"


def _data_label(source: str) -> str:
    return "sample data, not a live price" if source == "sample" else "live price"


class FindTickerArgs(BaseModel):
    company: str = Field(min_length=1, description="The company's name, for example Disney.")


class QuoteArgs(BaseModel):
    ticker: str = Field(min_length=1, description="The ticker symbol, for example DIS.")


class HistoryArgs(BaseModel):
    ticker: str = Field(min_length=1, description="The ticker symbol, for example DIS.")
    days: int = Field(default=30, ge=5, le=90, description="How many trading days to look back.")


def find_ticker(company: str) -> dict[str, Any]:
    wanted = company.strip().lower()
    matches = [
        {"ticker": ticker, "company": name}
        for ticker, name in WATCHLIST.items()
        if wanted in name.lower() or wanted == ticker.lower()
    ]
    if matches:
        return {"matches": matches}
    return {"matches": [], "note": "Not in Penny's list. Ask the child for the ticker symbol."}


def quote_facts(quote: Quote) -> dict[str, Any]:
    return {
        "company": quote.name,
        "ticker": quote.symbol,
        "price": dollars(quote.price_cents),
        "previous_close": dollars(quote.previous_close_cents),
        "change_since_previous_close": signed_pct(quote.change_pct),
        "direction_since_previous_close": direction(quote.change_pct),
        "size_of_change": size_pct(quote.change_pct),
        "as_of": quote.as_of.isoformat(),
        "source": quote.source,
        "data": _data_label(quote.source),
    }


def market_tools(market: MarketProvider) -> list[ToolSpec]:
    def get_quote(ticker: str) -> dict[str, Any]:
        return quote_facts(market.quote(ticker))

    def get_price_history(ticker: str, days: int) -> dict[str, Any]:
        history = market.history(ticker, days)
        closes = history.closes_cents
        move = daily_move_pct(closes)
        change = (closes[-1] - closes[0]) / closes[0] * 100
        return {
            "ticker": history.symbol,
            "trading_days": len(closes),
            "from": history.dates[0].isoformat(),
            "to": history.dates[-1].isoformat(),
            "start_price": dollars(closes[0]),
            "end_price": dollars(closes[-1]),
            "change_over_the_period": signed_pct(change),
            "direction_over_the_period": direction(change),
            "size_of_change": size_pct(change),
            "highest": dollars(max(closes)),
            "lowest": dollars(min(closes)),
            "typical_daily_move": "unknown" if move is None else f"{move:.2f}%",
            "source": history.source,
            "data": _data_label(history.source),
        }

    return [
        make_tool(
            "find_ticker",
            "Find a company's ticker symbol from its name, for companies in Penny's list. Call it "
            "before get_quote when the child names a company instead of a ticker.",
            FindTickerArgs,
            find_ticker,
        ),
        make_tool(
            "get_quote",
            "Get a company's latest share price and its change since the previous close. Use it "
            "for any 'how much is' or 'what is the price' question.",
            QuoteArgs,
            get_quote,
        ),
        make_tool(
            "get_price_history",
            "Summarise how a share price moved over recent trading days: start, end, highest, "
            "lowest and the typical daily move. Use it for 'has it gone up' or 'how bumpy' "
            "questions.",
            HistoryArgs,
            get_price_history,
        ),
    ]


def used_sample_data(result_runs: list[Any]) -> bool:
    for run in result_runs:
        try:
            if json.loads(run.output).get("source") == "sample":
                return True
        except (ValueError, AttributeError):
            continue
    return False


class MarketAgent:
    def __init__(
        self,
        llm: LLMClient,
        model: str,
        market: MarketProvider,
        *,
        name: str = "market",
        sink: TraceSink | None = None,
        max_steps: int = 5,
        max_tokens: int | None = 1200,
    ) -> None:
        self.llm = llm
        self.model = model
        self.market = market
        self.name = name
        self.sink = sink or NullTraceSink()
        self.max_steps = max_steps
        self.max_tokens = max_tokens

    def respond(self, request: AgentRequest) -> AgentReply:
        result = run_agent(
            self.llm,
            model=self.model,
            system=system_prompt(request, MARKET_ROLE, _RULES),
            messages=[*recent_history(request), Message.user(request.question)],
            tools=market_tools(self.market),
            sink=self.sink,
            trace_id=request.trace_id,
            agent=self.name,
            max_steps=self.max_steps,
            max_tokens=self.max_tokens,
        )
        reply = tool_backed_reply(result, MARKET_UNSURE)
        if (
            reply.text != MARKET_UNSURE
            and used_sample_data(successful_runs(result))
            and "sample" not in reply.text.lower()
        ):
            reply.text = f"{reply.text} {SAMPLE_NOTE}"
        return reply
