"""Saved-style sample data for offline use and demo mode. Never presented as a real price.

Prices are generated from a fixed seed per company, so they are stable between runs and tests.
Every quote says `source="sample"`, and the app labels it as sample data.
"""

from __future__ import annotations

import random
import zlib
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from penny.market.models import WATCHLIST, MarketDataError, PriceHistory, Quote, normalise_symbol

MAX_DAYS = 365


def _trading_days(end: date, count: int) -> list[date]:
    days: list[date] = []
    current = end
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return list(reversed(days))


class SampleProvider:
    name = "sample"

    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self._today = today

    def _closes(self, symbol: str, count: int) -> list[int]:
        rng = random.Random(zlib.crc32(symbol.encode()))
        price = rng.randint(2_000, 25_000)  # between $20 and $250
        closes = []
        for _ in range(MAX_DAYS):
            price = max(100, round(price * (1 + rng.gauss(0, 0.015))))
            closes.append(price)
        return closes[-count:]

    def _known(self, symbol: str) -> str:
        cleaned = normalise_symbol(symbol)
        if cleaned not in WATCHLIST:
            raise MarketDataError(f"there is no sample data for {cleaned}")
        return cleaned

    def history(self, symbol: str, days: int = 30) -> PriceHistory:
        cleaned = self._known(symbol)
        if not 2 <= days <= MAX_DAYS:
            raise MarketDataError(f"days must be from 2 to {MAX_DAYS}")
        return PriceHistory(
            symbol=cleaned,
            dates=_trading_days(self._today(), days),
            closes_cents=self._closes(cleaned, days),
            source=self.name,
            fetched_at=datetime.now(UTC),
        )

    def quote(self, symbol: str) -> Quote:
        recent = self.history(symbol, 2)
        return Quote(
            symbol=recent.symbol,
            name=WATCHLIST[recent.symbol],
            price_cents=recent.closes_cents[-1],
            previous_close_cents=recent.closes_cents[-2],
            as_of=recent.dates[-1],
            source=self.name,
            fetched_at=recent.fetched_at,
        )
