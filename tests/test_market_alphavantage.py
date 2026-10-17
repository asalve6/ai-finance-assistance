import io
import json
import urllib.error
from datetime import date

import pytest

from penny.market import alphavantage
from penny.market.alphavantage import AlphaVantageProvider, RequestBudget
from penny.market.cache import CachedProvider
from penny.market.chain import FallbackChain
from penny.market.factory import default_market
from penny.market.models import MarketDataError
from penny.market.sample import SampleProvider
from penny.market.yahoo import YahooProvider

KEY = "SECRET-KEY-123"

GLOBAL_QUOTE = {
    "Global Quote": {
        "01. symbol": "DIS",
        "05. price": "110.5900",
        "07. latest trading day": "2026-10-16",
        "08. previous close": "110.6800",
        "10. change percent": "-0.0813%",
    }
}
DAILY = {
    "Meta Data": {"2. Symbol": "DIS"},
    "Time Series (Daily)": {
        "2026-10-16": {"4. close": "110.5900"},
        "2026-10-14": {"4. close": "109.0000"},
        "2026-10-15": {"4. close": "110.6800"},
    },
}


class Fetch:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, params, timeout):
        self.calls.append((dict(params), timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def provider(*answers, limit=25, today=lambda: date(2026, 10, 16)):
    fetch = Fetch(*answers)
    budget = RequestBudget(limit=limit, today=today)
    return AlphaVantageProvider(KEY, fetch=fetch, budget=budget, timeout=4), fetch


# ------------------------------------------------------------------ answers


def test_a_quote_is_read_from_global_quote():
    av, fetch = provider(GLOBAL_QUOTE)
    q = av.quote("dis")
    assert (q.symbol, q.name, q.price_cents, q.previous_close_cents) == (
        "DIS",
        "Walt Disney",
        11059,
        11068,
    )
    assert (q.as_of, q.source) == (date(2026, 10, 16), "alphavantage")
    assert fetch.calls == [({"function": "GLOBAL_QUOTE", "symbol": "DIS", "apikey": KEY}, 4)]


def test_history_is_sorted_oldest_first_and_trimmed():
    av, fetch = provider(DAILY)
    history = av.history("DIS", 2)
    assert history.dates == [date(2026, 10, 15), date(2026, 10, 16)]
    assert history.closes_cents == [11068, 11059]
    assert fetch.calls[0][0]["function"] == "TIME_SERIES_DAILY"
    assert fetch.calls[0][0]["outputsize"] == "compact"


# ------------------------------------------------------------------ refusals and errors


def test_without_a_key_it_refuses_without_spending_a_request(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    fetch = Fetch()
    av = AlphaVantageProvider(fetch=fetch)
    with pytest.raises(MarketDataError, match="ALPHAVANTAGE_API_KEY is not set"):
        av.quote("DIS")
    assert fetch.calls == [] and av.budget.used == 0


def test_the_key_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "FROM-ENV")
    fetch = Fetch(GLOBAL_QUOTE)
    AlphaVantageProvider(fetch=fetch).quote("DIS")
    assert fetch.calls[0][0]["apikey"] == "FROM-ENV"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."
            },
            "Alpha Vantage: Thank you for using",
        ),
        ({"Information": "This is a premium endpoint."}, "premium endpoint"),
        ({"Error Message": "Invalid API call."}, "Invalid API call"),
        ({"Global Quote": {}}, "no quote for DIS"),
        ({}, "no quote for DIS"),
        ({"Global Quote": {"05. price": "abc"}}, "no quote for DIS"),
        (["not", "a", "dict"], "unexpected answer"),
    ],
)
def test_quote_problems_become_market_data_errors(payload, message):
    av, _ = provider(payload)
    with pytest.raises(MarketDataError, match=message):
        av.quote("DIS")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"Time Series (Daily)": {}}, "no prices for DIS"),
        ({"Time Series (Daily)": {"2026-10-16": {"1. open": "1"}}}, "unexpected shape"),
        ({"Time Series (Daily)": {"not-a-date": {"4. close": "1"}}}, "unexpected shape"),
    ],
)
def test_history_problems_become_market_data_errors(payload, message):
    av, _ = provider(payload)
    with pytest.raises(MarketDataError, match=message):
        av.history("DIS", 30)


@pytest.mark.parametrize("days", [1, 101])
def test_history_length_is_limited_to_what_the_free_tier_returns(days):
    av, fetch = provider()
    with pytest.raises(MarketDataError, match="from 2 to 100"):
        av.history("DIS", days)
    assert fetch.calls == []


# ------------------------------------------------------------------ the daily budget


def test_the_daily_budget_stops_requests_and_resets_the_next_day():
    day = {"today": date(2026, 10, 16)}
    av, fetch = provider(
        GLOBAL_QUOTE, GLOBAL_QUOTE, GLOBAL_QUOTE, limit=2, today=lambda: day["today"]
    )
    av.quote("DIS")
    av.quote("DIS")
    with pytest.raises(MarketDataError, match=r"daily request budget used up \(2\)"):
        av.quote("DIS")
    assert len(fetch.calls) == 2
    day["today"] = date(2026, 10, 17)
    av.quote("DIS")
    assert len(fetch.calls) == 3 and av.budget.used == 1


def test_failed_requests_still_count_against_the_budget():
    av, _ = provider({"Note": "rate limit"}, limit=5)
    with pytest.raises(MarketDataError):
        av.quote("DIS")
    assert av.budget.used == 1


def test_the_default_budget_is_the_free_tier_limit():
    assert RequestBudget().limit == 25 == alphavantage.DAILY_LIMIT


# ------------------------------------------------------------------ the real HTTP layer


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_json_reads_json_and_never_puts_the_key_in_errors(monkeypatch):
    seen = {}

    def ok(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        return Response(json.dumps({"hello": "world"}).encode())

    monkeypatch.setattr(alphavantage.urllib.request, "urlopen", ok)
    params = {"function": "GLOBAL_QUOTE", "symbol": "DIS", "apikey": KEY}
    assert alphavantage._fetch_json(params, 7) == {"hello": "world"}
    assert seen["url"].startswith("https://www.alphavantage.co/query?") and seen["timeout"] == 7

    failures = [
        urllib.error.HTTPError(seen["url"], 503, "busy", {}, None),
        urllib.error.URLError("no route to host"),
        TimeoutError("slow"),
    ]
    for failure in failures:

        def broken(request, timeout, failure=failure):
            raise failure

        monkeypatch.setattr(alphavantage.urllib.request, "urlopen", broken)
        with pytest.raises(MarketDataError) as raised:
            alphavantage._fetch_json(params, 7)
        assert KEY not in str(raised.value) and "apikey" not in str(raised.value)

    monkeypatch.setattr(
        alphavantage.urllib.request, "urlopen", lambda r, timeout: Response(b"<html>")
    )
    with pytest.raises(MarketDataError, match="not JSON"):
        alphavantage._fetch_json(params, 7)


# ------------------------------------------------------------------ the app's chain


def test_the_default_market_is_yahoo_then_alpha_vantage_then_sample_behind_a_cache():
    market = default_market()
    assert isinstance(market, CachedProvider) and isinstance(market.inner, FallbackChain)
    kinds = [type(p) for p in market.inner.providers]
    assert kinds == [YahooProvider, AlphaVantageProvider, SampleProvider]


def test_demo_mode_uses_only_sample_data():
    market = default_market(demo=True)
    assert [type(p) for p in market.inner.providers] == [SampleProvider]
    assert market.quote("DIS").is_sample


def test_without_a_key_the_chain_skips_alpha_vantage_cleanly(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)

    class YahooDown:
        name = "yfinance"

        def quote(self, symbol):
            raise MarketDataError("Yahoo Finance failed: throttled")

    chain = FallbackChain([YahooDown(), AlphaVantageProvider(fetch=Fetch()), SampleProvider()])
    assert chain.quote("DIS").source == "sample"
    assert [(a.provider, a.error) for a in chain.last_attempts] == [
        ("yfinance", "Yahoo Finance failed: throttled"),
        ("alphavantage", "ALPHAVANTAGE_API_KEY is not set"),
        ("sample", ""),
    ]
