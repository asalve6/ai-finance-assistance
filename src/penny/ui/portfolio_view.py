"""The Portfolio and Markets tab's logic: the practice-portfolio table, pricing it, and charts.

No Streamlit here, so every rule is easy to test. Prices come from the same market chain the
agents use (Yahoo Finance, then Alpha Vantage, then sample data), so the tab and Penny's answers
agree.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from penny.engines.portfolio import Holding, PortfolioReport, analyze
from penny.market.models import WATCHLIST, MarketDataError, PriceHistory, Quote
from penny.market.provider import MarketProvider

HISTORY_DAYS = 30
MAX_SHARES = 1000

SOURCE_NAMES = {
    "yfinance": "Yahoo Finance",
    "alphavantage": "Alpha Vantage",
    "sample": "sample data, not live prices",
}


def company_label(ticker: str) -> str:
    return f"{WATCHLIST[ticker]} ({ticker})"


COMPANY_LABELS = [company_label(ticker) for ticker in WATCHLIST]
_TICKER_FOR = {company_label(ticker): ticker for ticker in WATCHLIST}


def rows_for(holdings: dict[str, int]) -> list[dict[str, Any]]:
    """The editor's rows. Companies outside the list are left out: the table cannot show them."""
    return [
        {"Company": company_label(t), "Shares": n} for t, n in holdings.items() if t in WATCHLIST
    ]


def holdings_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    """What the child typed, made safe: blank or zero rows skipped, a repeated company added up."""
    holdings: dict[str, int] = {}
    for row in rows:
        ticker = _TICKER_FOR.get(row.get("Company") or "")
        shares = row.get("Shares")
        if ticker is None or shares is None or shares != shares:  # shares != shares: NaN
            continue
        shares = int(shares)
        if shares > 0:
            holdings[ticker] = min(MAX_SHARES, holdings.get(ticker, 0) + shares)
    return holdings


def served_by(sources: set[str]) -> str:
    names = sorted(SOURCE_NAMES.get(source, source) for source in sources)
    return "Prices from " + " and ".join(names) + "."


class PricedPortfolio(BaseModel):
    report: PortfolioReport
    quotes: dict[str, Quote]
    missing: list[str]  # tickers no provider could price, left out of the report

    @property
    def sources(self) -> set[str]:
        return {q.source for q in self.quotes.values()}


def price_portfolio(holdings: dict[str, int], market: MarketProvider) -> PricedPortfolio | None:
    """Price every holding and analyse the result. None when nothing could be priced."""
    quotes: dict[str, Quote] = {}
    missing: list[str] = []
    for ticker in holdings:
        try:
            quotes[ticker] = market.quote(ticker)
        except MarketDataError:
            missing.append(ticker)
    if not quotes:
        return None
    closes: dict[str, list[int]] = {}
    for ticker in quotes:
        try:
            closes[ticker] = market.history(ticker, HISTORY_DAYS).closes_cents
        except MarketDataError:
            pass  # bumpiness for this one is unknown, the rest still works
    report = analyze(
        [
            Holding(symbol=t, shares=holdings[t], price_cents=q.price_cents)
            for t, q in quotes.items()
        ],
        closes,
    )
    return PricedPortfolio(report=report, quotes=quotes, missing=missing)


def allocation_rows(priced: PricedPortfolio) -> list[dict[str, Any]]:
    """One row per company for the allocation chart, largest first."""
    return [
        {
            "Company": priced.quotes[p.symbol].name,
            "Share": round(p.weight_pct, 1),
            "Value": p.value_cents / 100,
            "Label": f"{p.weight_pct:.0f}%",
        }
        for p in priced.report.positions
    ]


def history_rows(history: PriceHistory) -> list[dict[str, Any]]:
    return [
        {"Date": day.isoformat(), "Price": cents / 100}
        for day, cents in zip(history.dates, history.closes_cents, strict=True)
    ]


def change_words(quote: Quote) -> str:
    """The quote card's delta, for example "-3.09% since the last close"."""
    return f"{quote.change_pct:+.2f}% since the last close"
