"""Try providers in order and use the first one that answers.

The planned order is Yahoo Finance, then Alpha Vantage, then the saved sample data, so the app
keeps working when a provider is down, rate limited or out of daily requests. The answer says
which provider gave it (`source`), and `last_attempts` records what failed along the way.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from penny.market.models import MarketDataError, PriceHistory, Quote
from penny.market.provider import MarketProvider

T = TypeVar("T")


class Attempt(BaseModel):
    provider: str
    ok: bool
    error: str = ""


class FallbackChain:
    name = "chain"

    def __init__(self, providers: Sequence[MarketProvider]) -> None:
        if not providers:
            raise ValueError("a chain needs at least one provider")
        self.providers = list(providers)
        self.last_attempts: list[Attempt] = []

    def _first(self, call: Callable[[MarketProvider], T]) -> T:
        self.last_attempts = []
        for provider in self.providers:
            try:
                answer = call(provider)
            except MarketDataError as exc:
                self.last_attempts.append(Attempt(provider=provider.name, ok=False, error=str(exc)))
                continue
            self.last_attempts.append(Attempt(provider=provider.name, ok=True))
            return answer
        problems = "; ".join(f"{a.provider}: {a.error}" for a in self.last_attempts)
        raise MarketDataError(f"no provider could answer ({problems})")

    def quote(self, symbol: str) -> Quote:
        return self._first(lambda provider: provider.quote(symbol))

    def history(self, symbol: str, days: int = 30) -> PriceHistory:
        return self._first(lambda provider: provider.history(symbol, days))
