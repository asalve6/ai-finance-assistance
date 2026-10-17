"""Alpha Vantage: the official fallback when Yahoo Finance fails. Needs ALPHAVANTAGE_API_KEY.

The free tier allows 25 requests a day, so every request is counted against a daily budget and
the provider refuses (a MarketDataError the chain moves past) once it is used up. The cache in
front of the chain means repeat questions do not spend requests at all.

The API key is sent with each request but never appears in an error message or a log.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from penny.market.models import (
    WATCHLIST,
    MarketDataError,
    PriceHistory,
    Quote,
    normalise_symbol,
)

URL = "https://www.alphavantage.co/query"
DAILY_LIMIT = 25
MAX_HISTORY_DAYS = 100  # what the free "compact" daily series returns


class RequestBudget:
    """Counts requests per calendar day and says no once the day's limit is reached."""

    def __init__(self, limit: int = DAILY_LIMIT, today: Callable[[], date] = date.today) -> None:
        self.limit = limit
        self._today = today
        self._day: date | None = None
        self.used = 0

    def spend(self) -> None:
        day = self._today()
        if day != self._day:
            self._day, self.used = day, 0
        if self.used >= self.limit:
            raise MarketDataError(f"Alpha Vantage daily request budget used up ({self.limit})")
        self.used += 1


def _fetch_json(params: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(params)}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:  # message names the status, never the URL or key
        raise MarketDataError(f"Alpha Vantage returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise MarketDataError(f"Could not reach Alpha Vantage ({reason})") from None
    except json.JSONDecodeError:
        raise MarketDataError("Alpha Vantage sent something that is not JSON") from None


class AlphaVantageProvider:
    name = "alphavantage"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        fetch: Callable[[dict[str, str], float], Any] = _fetch_json,
        budget: RequestBudget | None = None,
        timeout: float = 10,
    ) -> None:
        self._api_key = api_key
        self._fetch = fetch
        self.budget = budget or RequestBudget()
        self._timeout = timeout

    def _key(self) -> str:
        key = self._api_key or os.environ.get("ALPHAVANTAGE_API_KEY", "")
        if not key:
            raise MarketDataError("ALPHAVANTAGE_API_KEY is not set")
        return key

    def _call(self, function: str, symbol: str, **extra: str) -> dict[str, Any]:
        key = self._key()  # checked first, so a missing key costs nothing
        self.budget.spend()
        payload = self._fetch(
            {"function": function, "symbol": symbol, **extra, "apikey": key}, self._timeout
        )
        if not isinstance(payload, dict):
            raise MarketDataError("Alpha Vantage sent an unexpected answer")
        for field in ("Error Message", "Note", "Information"):
            if field in payload:  # unknown symbol, rate limit, or premium-only notice
                raise MarketDataError(f"Alpha Vantage: {str(payload[field])[:160]}")
        return payload

    def quote(self, symbol: str) -> Quote:
        cleaned = normalise_symbol(symbol)
        data = self._call("GLOBAL_QUOTE", cleaned).get("Global Quote") or {}
        try:
            price = round(float(data["05. price"]) * 100)
            previous = round(float(data["08. previous close"]) * 100)
            as_of = date.fromisoformat(data["07. latest trading day"])
        except (KeyError, ValueError):
            raise MarketDataError(f"Alpha Vantage has no quote for {cleaned}") from None
        return Quote(
            symbol=cleaned,
            name=WATCHLIST.get(cleaned, cleaned),
            price_cents=price,
            previous_close_cents=previous,
            as_of=as_of,
            source=self.name,
            fetched_at=datetime.now(UTC),
        )

    def history(self, symbol: str, days: int = 30) -> PriceHistory:
        cleaned = normalise_symbol(symbol)
        if not 2 <= days <= MAX_HISTORY_DAYS:
            raise MarketDataError(f"days must be from 2 to {MAX_HISTORY_DAYS}")
        series = self._call("TIME_SERIES_DAILY", cleaned, outputsize="compact").get(
            "Time Series (Daily)"
        )
        if not series:
            raise MarketDataError(f"Alpha Vantage has no prices for {cleaned}")
        try:
            points = sorted(
                (date.fromisoformat(day), round(float(row["4. close"]) * 100))
                for day, row in series.items()
            )[-days:]
        except (KeyError, ValueError, TypeError):
            raise MarketDataError("Alpha Vantage sent prices in an unexpected shape") from None
        return PriceHistory(
            symbol=cleaned,
            dates=[d for d, _ in points],
            closes_cents=[c for _, c in points],
            source=self.name,
            fetched_at=datetime.now(UTC),
        )
