from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from penny.graph.build import PennyGraph
from penny.market.factory import default_market
from penny.market.models import MarketDataError
from penny.market.sample import SampleProvider
from penny.observability import InMemoryTraceSink
from penny.ui import portfolio_view as view
from penny.ui.backend import Backend
from penny.ui.session import STARTER_PORTFOLIO, Player
from ui_helpers import launch, offline_backend

SAMPLE = SampleProvider(today=lambda: date(2026, 10, 16))


class Counting:
    """Sample prices that count every lookup, and can refuse some tickers."""

    name = "counting"

    def __init__(self, broken=()):
        self.calls = 0
        self.broken = set(broken)

    def quote(self, symbol):
        self.calls += 1
        if symbol in self.broken:
            raise MarketDataError(f"no price for {symbol}")
        return SAMPLE.quote(symbol)

    def history(self, symbol, days=30):
        self.calls += 1
        if symbol in self.broken:
            raise MarketDataError(f"no history for {symbol}")
        return SAMPLE.history(symbol, days)


# ------------------------------------------------------------------ the table


def test_rows_round_trip_through_the_editor():
    rows = view.rows_for({"DIS": 3, "KO": 5})
    assert rows == [
        {"Company": "Walt Disney (DIS)", "Shares": 3},
        {"Company": "Coca-Cola (KO)", "Shares": 5},
    ]
    assert view.holdings_from_rows(rows) == {"DIS": 3, "KO": 5}


def test_companies_outside_the_list_are_left_out_of_the_table():
    assert view.rows_for({"ZZZ": 1}) == []


def test_typed_rows_are_made_safe():
    nan = float("nan")
    rows = [
        {"Company": "Walt Disney (DIS)", "Shares": 2},
        {"Company": "Walt Disney (DIS)", "Shares": 3.0},  # repeated: added up
        {"Company": None, "Shares": 4},  # a new row with no company yet
        {"Company": "Nike (NKE)", "Shares": nan},  # a new row with no shares yet
        {"Company": "Apple (AAPL)", "Shares": 0},
        {"Company": "Not a company", "Shares": 1},
        {"Company": "Roblox (RBLX)", "Shares": 5000},  # capped
    ]
    assert view.holdings_from_rows(rows) == {"DIS": 5, "RBLX": view.MAX_SHARES}


def test_served_by_names_the_providers_in_plain_words():
    assert view.served_by({"yfinance"}) == "Prices from Yahoo Finance."
    assert view.served_by({"sample", "alphavantage"}) == (
        "Prices from Alpha Vantage and sample data, not live prices."
    )
    assert view.served_by({"other"}) == "Prices from other."


# ------------------------------------------------------------------ pricing


def test_pricing_the_portfolio_gives_the_report_and_chart_rows():
    priced = view.price_portfolio({"DIS": 3, "KO": 5}, Counting())
    assert priced.missing == [] and priced.sources == {"sample"}
    rows = view.allocation_rows(priced)
    assert {r["Company"] for r in rows} == {"Walt Disney", "Coca-Cola"}
    assert sum(r["Share"] for r in rows) == pytest.approx(100, abs=0.2)
    assert rows[0]["Share"] >= rows[1]["Share"]  # largest first
    assert priced.report.bumpiness != "Unknown"  # history was found


def test_a_company_without_a_price_is_left_out_and_named():
    priced = view.price_portfolio({"DIS": 3, "KO": 5}, Counting(broken={"KO"}))
    assert priced.missing == ["KO"]
    assert [p.symbol for p in priced.report.positions] == ["DIS"]


def test_nothing_priced_gives_none():
    assert view.price_portfolio({"KO": 5}, Counting(broken={"KO"})) is None


def test_history_rows_and_change_words():
    history = SAMPLE.history("DIS", 5)
    rows = view.history_rows(history)
    assert len(rows) == 5 and rows[-1] == {
        "Date": history.dates[-1].isoformat(),
        "Price": history.closes_cents[-1] / 100,
    }
    words = view.change_words(SAMPLE.quote("DIS"))
    assert words.endswith("% since the last close") and words[0] in "+-"


# ------------------------------------------------------------------ the player


def test_a_new_player_starts_with_the_starter_portfolio_as_a_copy():
    first, second = Player(), Player()
    assert first.practice_holdings == STARTER_PORTFOLIO
    first.practice_holdings["DIS"] = 99
    assert second.practice_holdings == STARTER_PORTFOLIO
    assert first.kid().practice_holdings == {**STARTER_PORTFOLIO, "DIS": 99}


def test_the_test_backend_uses_sample_prices():
    assert offline_backend().market.name == "chain"
    priced = view.price_portfolio({"DIS": 1}, offline_backend().market)
    assert priced.sources == {"sample"}


# ------------------------------------------------------------------ the tab, running


def tab_app(market=None, holdings=None) -> AppTest:
    def script():
        import streamlit as st

        from penny.ui import portfolio_tab

        portfolio_tab.render(st.session_state["player"])

    player = Player(started=True)
    if holdings is not None:
        player.practice_holdings = holdings
    sink = InMemoryTraceSink()
    backend = Backend(PennyGraph(sink=sink), sink, False, "x", market or default_market(demo=True))
    app = AppTest.from_function(script, default_timeout=30)
    app.session_state["player"] = player
    app.session_state["backend"] = backend
    app.run()
    assert not app.exception, app.exception
    return app


def captions(app) -> str:
    return " ".join(c.value for c in app.caption)


def test_the_tab_shows_the_starter_portfolio_and_a_quote():
    app = tab_app()
    assert [s.value for s in app.subheader] == ["My practice portfolio", "Look up a price"]
    labels = [m.label for m in app.metric]
    assert labels[:3] == ["Worth today", "Biggest share", "Bumpiness"]
    assert app.metric[1].value.endswith("%")
    assert "**Spread:**" in app.markdown[0].value
    assert labels[3] == "Walt Disney"  # the first company in the list
    assert app.metric[3].value.startswith("$")
    assert "since the last close" in app.metric[3].delta
    assert "sample data, not live prices" in captions(app)
    assert "Nothing is really bought or sold" in captions(app)
    assert app.session_state["player"].practice_holdings == STARTER_PORTFOLIO


def test_picking_another_company_shows_its_price():
    app = tab_app()
    app.selectbox(key="market_pick").select("RBLX").run()
    assert not app.exception
    assert app.metric[3].label == "Roblox"


def test_an_empty_portfolio_asks_for_a_company():
    app = tab_app(holdings={})
    assert "Add a company" in app.info[0].value
    assert [m.label for m in app.metric] == ["Walt Disney"]  # only the quote card


def test_missing_prices_are_said_kindly():
    app = tab_app(market=Counting(broken={"KO"}))
    assert "No price found for KO" in app.warning[0].value
    app = tab_app(market=Counting(broken=set(STARTER_PORTFOLIO) | {"DIS"}))
    assert [w.value for w in app.warning] == [
        "Penny could not find prices right now. Please try again later.",
        "Penny could not find this price right now. Please try again later.",
    ]


def test_the_closed_tab_looks_up_no_prices():
    market = Counting()
    sink = InMemoryTraceSink()
    backend = Backend(PennyGraph(sink=sink), sink, False, "x", market)
    app = launch(backend=backend, player=Player(started=True))
    assert [t.label for t in app.tabs][2] == "Portfolio and Markets"
    assert market.calls == 0
