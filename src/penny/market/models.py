"""What a market provider returns, and the companies Penny knows to talk about."""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel

# Companies a child is likely to know. The Market agent can look up any ticker, but these are the
# suggestions and the ones the offline sample data covers.
WATCHLIST: dict[str, str] = {
    "DIS": "Walt Disney",
    "NTDOY": "Nintendo",
    "RBLX": "Roblox",
    "MCD": "McDonald's",
    "NKE": "Nike",
    "MAT": "Mattel",
    "HAS": "Hasbro",
    "AAPL": "Apple",
    "KO": "Coca-Cola",
    "SONY": "Sony",
}

_TICKER = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")


class MarketDataError(RuntimeError):
    """A provider could not answer (unknown ticker, network trouble, rate limit, budget used up)."""


def normalise_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if not _TICKER.match(cleaned):
        raise MarketDataError(f"'{symbol}' does not look like a stock ticker")
    return cleaned


class Quote(BaseModel):
    symbol: str
    name: str
    price_cents: int
    previous_close_cents: int
    as_of: date
    source: str  # which provider answered, for example "yfinance" or "sample"
    fetched_at: datetime

    @property
    def change_pct(self) -> float:
        return (self.price_cents - self.previous_close_cents) / self.previous_close_cents * 100

    @property
    def is_sample(self) -> bool:
        return self.source == "sample"


class PriceHistory(BaseModel):
    symbol: str
    dates: list[date]
    closes_cents: list[int]  # oldest first
    source: str
    fetched_at: datetime
