"""The interface every market data provider implements."""

from __future__ import annotations

from typing import Protocol

from penny.market.models import PriceHistory, Quote


class MarketProvider(Protocol):
    name: str

    def quote(self, symbol: str) -> Quote: ...

    def history(self, symbol: str, days: int = 30) -> PriceHistory: ...
