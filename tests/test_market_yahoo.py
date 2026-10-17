from datetime import date

import pandas as pd
import pytest

from penny.market.models import MarketDataError
from penny.market.yahoo import YahooProvider, _period_for


def frame(closes, end="2026-10-16"):
    index = pd.bdate_range(end=end, periods=len(closes), tz="America/New_York")
    return pd.DataFrame({"Open": closes, "Close": closes}, index=index)


class FakeTicker:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def provider_with(result):
    fake = FakeTicker(result)
    asked: list[str] = []

    def make(symbol):
        asked.append(symbol)
        return fake

    return YahooProvider(ticker=make, timeout=3), fake, asked


@pytest.mark.parametrize(
    ("days", "period"),
    [
        (2, "5d"),
        (5, "5d"),
        (6, "1mo"),
        (21, "1mo"),
        (30, "3mo"),
        (90, "6mo"),
        (200, "1y"),
        (504, "2y"),
    ],
)
def test_the_smallest_period_covering_the_days_is_used(days, period):
    assert _period_for(days) == period


def test_too_many_days_is_refused():
    with pytest.raises(MarketDataError, match="at most 504"):
        _period_for(505)


def test_a_quote_comes_from_the_last_two_closes_in_cents():
    provider, fake, asked = provider_with(frame([109.0, 110.68, 110.589996]))
    q = provider.quote(" dis ")
    assert asked == ["DIS"]
    assert (q.price_cents, q.previous_close_cents) == (11059, 11068)
    assert (q.name, q.source, q.as_of) == ("Walt Disney", "yfinance", date(2026, 10, 16))
    assert fake.calls == [{"period": "5d", "auto_adjust": False, "timeout": 3}]


def test_a_ticker_outside_the_watchlist_is_named_by_its_symbol():
    provider, _, _ = provider_with(frame([10.0, 11.0]))
    assert provider.quote("TSLA").name == "TSLA"


def test_history_trims_to_the_days_asked_and_skips_gaps():
    closes = [100.0, None, 101.0, 102.0, 103.0, 104.0]
    provider, fake, _ = provider_with(frame(closes))
    history = provider.history("ko", 3)
    assert history.closes_cents == [10200, 10300, 10400]
    assert history.dates[-1] == date(2026, 10, 16) and len(history.dates) == 3
    assert (history.symbol, history.source) == ("KO", "yfinance")
    assert fake.calls[0]["period"] == "5d"


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (pd.DataFrame(), "has no prices for DIS"),
        (None, "has no prices for DIS"),
        (pd.DataFrame({"Open": [1.0]}), "has no prices for DIS"),
        (frame([float("nan"), float("nan")]), "has no prices for DIS"),
        (frame([10.0]), "too little data for DIS"),
        (
            ConnectionError("network unreachable"),
            "Yahoo Finance failed: ConnectionError: network unreachable",
        ),
        (RuntimeError("Too Many Requests. Rate limited."), "Rate limited"),
    ],
)
def test_every_kind_of_failure_becomes_a_market_data_error(result, message):
    provider, _, _ = provider_with(result)
    with pytest.raises(MarketDataError, match=message):
        provider.quote("DIS")


def test_bad_tickers_and_lengths_are_refused_before_any_request():
    provider, _, asked = provider_with(frame([1.0, 2.0]))
    with pytest.raises(MarketDataError, match="does not look like a stock ticker"):
        provider.quote("not a ticker")
    with pytest.raises(MarketDataError, match="at least 2"):
        provider.history("DIS", 1)
    assert asked == []


def test_the_default_ticker_comes_from_yfinance():
    from penny.market import yahoo

    ticker = yahoo._default_ticker("DIS")
    assert type(ticker).__name__ == "Ticker" and ticker.ticker == "DIS"
