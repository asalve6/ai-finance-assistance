"""The Portfolio Analysis agent: the child's practice portfolio, explained.

The holdings come with the request (`KidContext.practice_holdings`). Prices come from the market
chain and the maths from `engines/portfolio.py`, through two tools:

- `analyze_my_portfolio`  value, each company's share, spread and bumpiness, with plain meanings
- `try_a_change`          the same summary before and after adding or removing practice shares

It is practice money only: the agent can suggest trying a change in the practice portfolio, but
never tells a child to buy or sell real shares. An empty portfolio gets a fixed reply without
calling the model. The shared grounding rules apply: numbers only from tools, sample data always
disclosed.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from penny.agents.grounding import disclose_sample_data, tool_backed_reply
from penny.agents.loop import ToolRun, run_agent
from penny.agents.prompts import recent_history, system_prompt
from penny.agents.tools import make_tool
from penny.contracts import LLMClient, Message, ToolSpec, TraceSink
from penny.engines.portfolio import Holding, analyze
from penny.graph.types import AgentReply, AgentRequest
from penny.market.models import MarketDataError, normalise_symbol
from penny.market.provider import MarketProvider
from penny.money import dollars
from penny.observability import NullTraceSink

PORTFOLIO_ROLE = (
    "You help children understand their practice portfolio: what it is worth, how spread out the "
    "money is, and how bumpy the prices are. It is practice money only."
)

PORTFOLIO_UNSURE = (
    "I can look at your practice portfolio with you. Ask me how spread out it is, or what would "
    "happen if you changed it."
)

NO_PORTFOLIO = (
    "You do not have a practice portfolio yet. Open the Portfolio and Markets tab to add some "
    "companies, then ask me again."
)

HISTORY_DAYS = 30
MAX_SHARE_CHANGE = 100

# The engine's labels, said the way a child would say them ("concentrated" is a hard word).
SPREAD_WORDS = {
    "Concentrated": "mostly in one company",
    "Somewhat spread": "somewhat spread out",
    "Spread out": "spread out",
}

SPREAD_MEANS = {
    "Concentrated": "Most of the money is in one company, so that company's ups and downs "
    "matter a lot.",
    "Somewhat spread": "The money is in a few companies, but one of them is a big part.",
    "Spread out": "The money is spread across several companies, so one company having a bad "
    "day hurts less.",
}

BUMPINESS_MEANS = {
    "Calmer": "The prices usually move less than 1% in a day.",
    "Medium": "The prices usually move about 1% to 2% in a day.",
    "Bumpier": "The prices often move more than 2% in a day.",
    "Unknown": "There is not enough price history to tell.",
}

_RULES = """\
How to answer:
- Never state a value, a share or a percentage yourself. The analysis of the child's portfolio is
  already given to you below the question: use it, even for a follow-up. To show what a change
  would do, call try_a_change.
- Say amounts exactly the way the tools wrote them, and give each number once. Pick the one or two
  numbers that matter most for the question; you do not need to list every holding.
- Explain the spread and the bumpiness in plain words, using the tool's own words. Spreading money
  across different companies means one company's bad day hurts the whole portfolio less.
- Describe the portfolio; do not tell the child what to change, add, buy or sell. If they want to
  see a change, they can ask "what if" and you show it with try_a_change.
- If the child asks whether to keep it, change it, or for advice: say that Penny can't give advice,
  and do not say yes or no or what to do. Do not name any change, such as adding or selling
  shares. Say what the numbers show and what spreading money out does. You may say they can ask a
  "what if" question to try a change in the practice portfolio, and suggest talking it over with
  a grown-up.
- If a tool says the prices are sample data, say so in your answer.
- Keep the jar and drops comparison for saving questions.
- Write plain sentences and stay inside the sentence limit below. No lists, headings or bold."""


class NoArgs(BaseModel):
    pass


class ChangeArgs(BaseModel):
    ticker: str = Field(min_length=1, description="The ticker symbol, for example KO.")
    shares_change: int = Field(
        ge=-MAX_SHARE_CHANGE,
        le=MAX_SHARE_CHANGE,
        description="Practice shares to add (positive) or remove (negative). Not zero.",
    )


def summarise(holdings: dict[str, int], market: MarketProvider) -> dict[str, Any]:
    """Price the holdings and describe the portfolio in ready-to-say words."""
    quotes = {symbol: market.quote(symbol) for symbol in holdings}
    closes: dict[str, list[int]] = {}
    for symbol in holdings:
        try:
            closes[symbol] = market.history(symbol, HISTORY_DAYS).closes_cents
        except MarketDataError:
            pass  # bumpiness for this one is unknown, the rest still works
    report = analyze(
        [
            Holding(symbol=s, shares=n, price_cents=quotes[s].price_cents)
            for s, n in holdings.items()
        ],
        closes,
    )
    sample = any(q.is_sample for q in quotes.values())
    return {
        "total_value": dollars(report.total_cents),
        "holdings": [
            {
                "company": quotes[p.symbol].name,
                "ticker": p.symbol,
                "shares": p.shares,
                "price": dollars(quotes[p.symbol].price_cents),
                "value": dollars(p.value_cents),
                "share_of_portfolio": f"{p.weight_pct:.0f}%",
            }
            for p in report.positions
        ],
        "spread": SPREAD_WORDS[report.spread],
        "spread_means": SPREAD_MEANS[report.spread],
        "effective_number_of_companies": f"{report.effective_holdings:.1f}",
        "bumpiness": report.bumpiness,
        "bumpiness_means": BUMPINESS_MEANS[report.bumpiness],
        "typical_daily_move": "unknown"
        if report.daily_move_pct is None
        else f"{report.daily_move_pct:.2f}%",
        "source": "sample" if sample else ", ".join(sorted({q.source for q in quotes.values()})),
        "data": "sample data, not live prices" if sample else "live prices",
    }


def changed(holdings: dict[str, int], ticker: str, shares_change: int) -> dict[str, int]:
    """The practice holdings after a change. Removing all shares drops the company."""
    if shares_change == 0:
        raise ValueError("shares_change cannot be zero")
    symbol = normalise_symbol(ticker)
    new = dict(holdings)
    count = new.get(symbol, 0) + shares_change
    if count < 0:
        raise ValueError(f"you only have {new.get(symbol, 0)} practice shares of {symbol}")
    if count == 0:
        new.pop(symbol, None)
    else:
        new[symbol] = count
    if not new:
        raise ValueError("that would leave the practice portfolio empty")
    return new


def portfolio_tools(holdings: dict[str, int], market: MarketProvider) -> list[ToolSpec]:
    def analyze_my_portfolio() -> dict[str, Any]:
        return summarise(holdings, market)

    def try_a_change(ticker: str, shares_change: int) -> dict[str, Any]:
        after = changed(holdings, ticker, shares_change)
        before_summary, after_summary = summarise(holdings, market), summarise(after, market)
        verb = "add" if shares_change > 0 else "remove"
        sample = "sample" in (before_summary["source"], after_summary["source"])
        return {
            "change": f"{verb} {abs(shares_change)} practice shares of {normalise_symbol(ticker)}",
            "before": before_summary,
            "after": after_summary,
            "source": "sample" if sample else after_summary["source"],
            "note": "Practice only. Nothing is really bought or sold.",
        }

    return [
        make_tool(
            "analyze_my_portfolio",
            "Look at the child's practice portfolio: total value, each company's share, how "
            "spread out it is and how bumpy the prices are. Call it before talking about the "
            "portfolio.",
            NoArgs,
            analyze_my_portfolio,
        ),
        make_tool(
            "try_a_change",
            "Show what the practice portfolio would look like after adding or removing some "
            "practice shares of one company, before and after. Use it for 'what if' questions. "
            "It does not change the real practice portfolio.",
            ChangeArgs,
            try_a_change,
        ),
    ]


class PortfolioAgent:
    def __init__(
        self,
        llm: LLMClient,
        model: str,
        market: MarketProvider,
        *,
        name: str = "portfolio",
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

    def _analysis(self, holdings: dict[str, int]) -> ToolRun | None:
        """The portfolio analysis, run in code before the model writes anything. Without it a
        follow-up such as "should I keep it?" is answered from memory, with no evidence."""
        try:
            summary = summarise(holdings, self.market)
        except MarketDataError:
            return None  # the model's own tool will report the problem
        return ToolRun(name="analyze_my_portfolio", input={}, output=json.dumps(summary))

    def respond(self, request: AgentRequest) -> AgentReply:
        holdings = request.kid.practice_holdings
        if not holdings:
            return AgentReply(text=NO_PORTFOLIO)  # nothing to analyse, so no model call
        analysis = self._analysis(holdings)
        question = request.question
        if analysis is not None:
            question += f"\n\nAnalysis of the child's practice portfolio:\n{analysis.output}"
        result = run_agent(
            self.llm,
            model=self.model,
            system=system_prompt(request, PORTFOLIO_ROLE, _RULES),
            messages=[*recent_history(request), Message.user(question)],
            tools=portfolio_tools(holdings, self.market),
            sink=self.sink,
            trace_id=request.trace_id,
            agent=self.name,
            max_steps=self.max_steps,
            max_tokens=self.max_tokens,
        )
        if analysis is not None:
            result.tool_runs.insert(0, analysis)  # evidence for the Guardian, like any tool run
        reply = tool_backed_reply(result, PORTFOLIO_UNSURE)
        return disclose_sample_data(reply, result, {PORTFOLIO_UNSURE})
