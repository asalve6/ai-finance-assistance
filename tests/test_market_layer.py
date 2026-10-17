from datetime import UTC, date, datetime

import pytest

from penny.market.cache import DEFAULT_TTL_SECONDS, CachedProvider
from penny.market.chain import FallbackChain
from penny.market.models import WATCHLIST, MarketDataError, PriceHistory, Quote, normalise_symbol
from penny.market.sample import SampleProvider

FRIDAY = date(2026, 10, 16)


def quote(symbol="DIS", price=11000, previous=10000, source="fake") -> Quote:
    return Quote(
        symbol=symbol,
        name="Walt Disney",
        price_cents=price,
        previous_close_cents=previous,
        as_of=FRIDAY,
        source=source,
        fetched_at=datetime(2026, 10, 16, tzinfo=UTC),
    )


class Fake:
    """A provider that answers or fails as told, and counts its calls."""

    def __init__(self, name="fake", fail_with=None):
        self.name = name
        self.fail_with = fail_with
        self.calls: list[tuple] = []

    def quote(self, symbol):
        self.calls.append(("quote", symbol))
        if self.fail_with:
            raise MarketDataError(self.fail_with)
        return quote(symbol, source=self.name)

    def history(self, symbol, days=30):
        self.calls.append(("history", symbol, days))
        if self.fail_with:
            raise MarketDataError(self.fail_with)
        return PriceHistory(
            symbol=symbol, dates=[FRIDAY], closes_cents=[100], source=self.name,
            fetched_at=datetime(2026, 10, 16, tzinfo=UTC),
        )  # fmt: skip


# ------------------------------------------------------------------ models


@pytest.mark.parametrize(
    ("raw", "clean"),
    [("dis", "DIS"), ("  ntdoy ", "NTDOY"), ("BRK.B", "BRK.B"), ("RDS-A", "RDS-A")],
)
def test_symbols_are_cleaned_up(raw, clean):
    assert normalise_symbol(raw) == clean


@pytest.mark.parametrize(
    "raw", ["", "  ", "123", "DIS; drop table", "A" * 11, "$DIS", "Disney Company"]
)
def test_things_that_are_not_tickers_are_refused(raw):
    with pytest.raises(MarketDataError, match="does not look like a stock ticker"):
        normalise_symbol(raw)


def test_a_quote_knows_its_daily_change_and_whether_it_is_sample_data():
    assert quote(price=11000, previous=10000).change_pct == pytest.approx(10.0)
    assert quote(price=9500, previous=10000).change_pct == pytest.approx(-5.0)
    assert quote(source="sample").is_sample and not quote(source="yfinance").is_sample


def test_the_watchlist_is_companies_children_know():
    assert len(WATCHLIST) == 10 and WATCHLIST["RBLX"] == "Roblox"
    assert all(normalise_symbol(s) == s for s in WATCHLIST)


# ------------------------------------------------------------------ sample provider


def test_sample_history_is_stable_labelled_and_on_trading_days():
    provider = SampleProvider(today=lambda: FRIDAY)
    first, again = provider.history("dis", 30), provider.history("DIS", 30)
    assert first.closes_cents == again.closes_cents and len(first.closes_cents) == 30
    assert first.source == "sample" and first.symbol == "DIS"
    assert first.dates[-1] == FRIDAY and all(d.weekday() < 5 for d in first.dates)
    assert first.dates == sorted(first.dates)
    assert all(c >= 100 for c in first.closes_cents)


def test_sample_quote_matches_the_last_two_days_of_history():
    provider = SampleProvider(today=lambda: FRIDAY)
    history, q = provider.history("NTDOY", 30), provider.quote("ntdoy")
    assert q.price_cents == history.closes_cents[-1]
    assert q.previous_close_cents == history.closes_cents[-2]
    assert (q.name, q.as_of, q.is_sample) == ("Nintendo", FRIDAY, True)


def test_different_companies_get_different_sample_prices():
    provider = SampleProvider(today=lambda: FRIDAY)
    prices = {provider.quote(s).price_cents for s in WATCHLIST}
    assert len(prices) == len(WATCHLIST)


def test_a_shorter_history_is_the_end_of_the_longer_one():
    provider = SampleProvider(today=lambda: FRIDAY)
    assert provider.history("KO", 10).closes_cents == provider.history("KO", 60).closes_cents[-10:]


def test_sample_data_only_covers_the_watchlist_and_sensible_lengths():
    provider = SampleProvider(today=lambda: FRIDAY)
    with pytest.raises(MarketDataError, match="no sample data for TSLA"):
        provider.quote("TSLA")
    for days in (1, 366):
        with pytest.raises(MarketDataError, match="days must be"):
            provider.history("DIS", days)


def test_weekend_today_still_ends_on_a_weekday():
    sunday = date(2026, 10, 18)
    history = SampleProvider(today=lambda: sunday).history("DIS", 5)
    assert history.dates[-1] == FRIDAY


# ------------------------------------------------------------------ cache


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_repeat_questions_within_the_ttl_are_answered_from_the_cache():
    inner, clock = Fake(), Clock()
    cached = CachedProvider(inner, ttl_seconds=60, clock=clock)
    first = cached.quote("dis")
    clock.now += 59
    assert cached.quote("DIS") is first
    assert inner.calls == [("quote", "DIS")]


def test_after_the_ttl_the_provider_is_asked_again():
    inner, clock = Fake(), Clock()
    cached = CachedProvider(inner, ttl_seconds=60, clock=clock)
    cached.quote("DIS")
    clock.now += 60
    cached.quote("DIS")
    assert len(inner.calls) == 2


def test_quotes_and_histories_of_different_lengths_are_cached_separately():
    inner = Fake()
    cached = CachedProvider(inner, clock=Clock())
    cached.quote("DIS")
    cached.history("DIS", 30)
    cached.history("DIS", 30)
    cached.history("DIS", 90)
    cached.quote("KO")
    assert inner.calls == [
        ("quote", "DIS"),
        ("history", "DIS", 30),
        ("history", "DIS", 90),
        ("quote", "KO"),
    ]


def test_failures_are_not_cached():
    inner = Fake(fail_with="network down")
    cached = CachedProvider(inner, clock=Clock())
    for _ in range(2):
        with pytest.raises(MarketDataError):
            cached.quote("DIS")
    assert len(inner.calls) == 2
    inner.fail_with = None
    assert cached.quote("DIS").source == "fake"


def test_the_cache_keeps_the_providers_name_and_a_30_minute_default():
    cached = CachedProvider(Fake(name="yfinance"))
    assert cached.name == "yfinance" and DEFAULT_TTL_SECONDS == 1800 and cached.ttl_seconds == 1800


def test_bad_symbols_never_reach_the_provider():
    inner = Fake()
    with pytest.raises(MarketDataError):
        CachedProvider(inner).quote("not a ticker")
    assert inner.calls == []


# ------------------------------------------------------------------ fallback chain


def test_the_first_provider_that_answers_wins_and_the_rest_are_not_asked():
    first, second = Fake("yfinance"), Fake("alphavantage")
    chain = FallbackChain([first, second])
    assert chain.quote("DIS").source == "yfinance"
    assert second.calls == []
    assert [(a.provider, a.ok) for a in chain.last_attempts] == [("yfinance", True)]


def test_a_failing_provider_falls_through_to_the_next_and_is_recorded():
    chain = FallbackChain(
        [
            Fake("yfinance", fail_with="429 too many requests"),
            Fake("alphavantage", fail_with="daily budget used up"),
            SampleProvider(today=lambda: FRIDAY),
        ]
    )
    q = chain.quote("DIS")
    assert q.source == "sample" and q.is_sample
    assert [(a.provider, a.ok, a.error) for a in chain.last_attempts] == [
        ("yfinance", False, "429 too many requests"),
        ("alphavantage", False, "daily budget used up"),
        ("sample", True, ""),
    ]
    assert chain.history("DIS", 10).source == "sample"


def test_when_every_provider_fails_the_error_lists_why():
    chain = FallbackChain(
        [Fake("yfinance", fail_with="down"), SampleProvider(today=lambda: FRIDAY)]
    )
    with pytest.raises(
        MarketDataError,
        match=r"no provider could answer \(yfinance: down; sample: there is no sample data for TSLA\)",
    ):
        chain.quote("TSLA")


def test_each_call_starts_a_fresh_attempt_list():
    flaky = Fake("yfinance", fail_with="down")
    chain = FallbackChain([flaky, Fake("backup")])
    chain.quote("DIS")
    flaky.fail_with = None
    chain.quote("DIS")
    assert [(a.provider, a.ok) for a in chain.last_attempts] == [("yfinance", True)]


def test_a_chain_needs_providers_and_works_behind_a_cache():
    with pytest.raises(ValueError):
        FallbackChain([])
    primary = Fake("yfinance")
    cached = CachedProvider(FallbackChain([primary]), clock=Clock())
    cached.quote("DIS")
    cached.quote("DIS")
    assert len(primary.calls) == 1
