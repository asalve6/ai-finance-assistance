"""Keep answers for a while so repeat questions do not spend API calls (Alpha Vantage allows 25 a
day). Failures are never cached, so a provider that recovers is used again straight away."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from penny.market.models import PriceHistory, Quote, normalise_symbol
from penny.market.provider import MarketProvider

DEFAULT_TTL_SECONDS = 30 * 60


class CachedProvider:
    def __init__(
        self,
        inner: MarketProvider,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def _get(self, key: tuple[Any, ...], fetch: Callable[[], Any]) -> Any:
        now = self._clock()
        hit = self._entries.get(key)
        if hit is not None and now - hit[0] < self.ttl_seconds:
            return hit[1]
        value = fetch()  # raises on failure, so failures are not stored
        self._entries[key] = (now, value)
        return value

    def quote(self, symbol: str) -> Quote:
        cleaned = normalise_symbol(symbol)
        return self._get(("quote", cleaned), lambda: self.inner.quote(cleaned))

    def history(self, symbol: str, days: int = 30) -> PriceHistory:
        cleaned = normalise_symbol(symbol)
        return self._get(("history", cleaned, days), lambda: self.inner.history(cleaned, days))
