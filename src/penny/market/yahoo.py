"""Yahoo Finance through the `yfinance` package. No key needed, but it is unofficial: Yahoo can
throttle or change things, which is why it sits first in a fallback chain, not alone.

yfinance reports most problems by returning an empty table (and printing a message) rather than
raising, so an empty result is treated as "no data". Anything it does raise becomes a
MarketDataError, so the chain can move on to the next provider.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from penny.market.models import (
    WATCHLIST,
    MarketDataError,
    PriceHistory,
    Quote,
    normalise_symbol,
)

# yfinance takes named periods. Pick the smallest one that covers the trading days asked for.
_PERIODS = ((5, "5d"), (21, "1mo"), (63, "3mo"), (126, "6mo"), (252, "1y"), (504, "2y"))


def _period_for(days: int) -> str:
    for trading_days, period in _PERIODS:
        if days <= trading_days:
            return period
    raise MarketDataError(f"days must be at most {_PERIODS[-1][0]}")


def _default_ticker(symbol: str) -> Any:
    import yfinance

    return yfinance.Ticker(symbol)


class YahooProvider:
    name = "yfinance"

    def __init__(self, ticker: Callable[[str], Any] = _default_ticker, timeout: float = 10) -> None:
        self._ticker = ticker  # injectable, so tests never touch the network
        self._timeout = timeout

    def _closes(self, symbol: str, days: int) -> tuple[list, list[int]]:
        try:
            frame = self._ticker(symbol).history(
                period=_period_for(days), auto_adjust=False, timeout=self._timeout
            )
        except MarketDataError:
            raise
        except Exception as exc:  # network errors, throttling, parsing problems
            raise MarketDataError(f"Yahoo Finance failed: {type(exc).__name__}: {exc}") from exc
        if frame is None or frame.empty or "Close" not in frame:
            raise MarketDataError(f"Yahoo Finance has no prices for {symbol}")
        closes = frame["Close"].dropna().tail(days)
        if closes.empty:
            raise MarketDataError(f"Yahoo Finance has no prices for {symbol}")
        dates = [stamp.date() for stamp in closes.index]
        return dates, [round(float(price) * 100) for price in closes]

    def history(self, symbol: str, days: int = 30) -> PriceHistory:
        cleaned = normalise_symbol(symbol)
        if days < 2:
            raise MarketDataError("days must be at least 2")
        dates, closes = self._closes(cleaned, days)
        return PriceHistory(
            symbol=cleaned,
            dates=dates,
            closes_cents=closes,
            source=self.name,
            fetched_at=datetime.now(UTC),
        )

    def quote(self, symbol: str) -> Quote:
        cleaned = normalise_symbol(symbol)
        dates, closes = self._closes(cleaned, 5)
        if len(closes) < 2:
            raise MarketDataError(f"Yahoo Finance returned too little data for {cleaned}")
        return Quote(
            symbol=cleaned,
            name=WATCHLIST.get(cleaned, cleaned),
            price_cents=closes[-1],
            previous_close_cents=closes[-2],
            as_of=dates[-1],
            source=self.name,
            fetched_at=datetime.now(UTC),
        )
