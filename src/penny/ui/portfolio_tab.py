"""The Portfolio and Markets tab: the practice portfolio, and one company's price and chart."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from penny.agents.portfolio_agent import BUMPINESS_MEANS, SPREAD_MEANS, SPREAD_WORDS
from penny.market.models import WATCHLIST, MarketDataError
from penny.ui import portfolio_view as view
from penny.ui.chat import get_backend
from penny.ui.session import Player
from penny.ui.text import dollars, md

ROWS_KEY = "portfolio_rows"  # the editor's starting table, kept while the tab is open


def forget() -> None:
    """Called while the tab is closed: its table restarts from the player's holdings."""
    st.session_state.pop(ROWS_KEY, None)


def render(player: Player) -> None:
    market = get_backend().market
    portfolio_column, market_column = st.columns([3, 2], gap="large")
    with portfolio_column:
        _portfolio(player, market)
    with market_column:
        _market(market)


def _portfolio(player: Player, market) -> None:
    st.subheader("My practice portfolio")
    st.caption("Practice money only. Nothing is really bought or sold.")
    if ROWS_KEY not in st.session_state:
        st.session_state[ROWS_KEY] = pd.DataFrame(
            view.rows_for(player.practice_holdings), columns=["Company", "Shares"]
        )
    edited = st.data_editor(
        st.session_state[ROWS_KEY],
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "Company": st.column_config.SelectboxColumn(
                "Company", options=view.COMPANY_LABELS, required=True, width="medium"
            ),
            "Shares": st.column_config.NumberColumn(
                "Shares", min_value=1, max_value=view.MAX_SHARES, step=1, required=True
            ),
        },
        key="portfolio_editor",
        alt="Practice portfolio: each company and how many practice shares",
    )
    player.practice_holdings = view.holdings_from_rows(edited.to_dict("records"))
    if not player.practice_holdings:
        st.info("Add a company and some practice shares to see your portfolio.")
        return

    with st.spinner("Looking up prices..."):
        priced = view.price_portfolio(player.practice_holdings, market)
    if priced is None:
        st.warning("Penny could not find prices right now. Please try again later.")
        return
    if priced.missing:
        st.warning(f"No price found for {', '.join(priced.missing)}, so it is left out.")

    report = priced.report
    with st.container(horizontal=True):
        st.metric("Worth today", dollars(report.total_cents), border=True)
        st.metric("Biggest share", f"{report.largest_weight_pct:.0f}%", border=True)
        st.metric("Bumpiness", report.bumpiness, border=True)
    spread = SPREAD_WORDS[report.spread]
    st.markdown(
        md(
            f"**Spread:** {spread}. {SPREAD_MEANS[report.spread]}  \n"
            f"**Bumpiness:** {report.bumpiness.lower()}. {BUMPINESS_MEANS[report.bumpiness]}"
        )
    )
    _allocation_chart(priced)
    st.caption(md(view.served_by(priced.sources)))
    st.caption('Ask Penny in the Chat tab: "Is my portfolio spread out?"')


def _allocation_chart(priced: view.PricedPortfolio) -> None:
    rows = view.allocation_rows(priced)
    base = alt.Chart(alt.Data(values=rows)).encode(
        y=alt.Y("Company:N", sort="-x", title=None),
        x=alt.X("Share:Q", title="Share of the portfolio (%)", scale=alt.Scale(domain=[0, 100])),
    )
    bars = base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4).encode(
        tooltip=[
            alt.Tooltip("Company:N"),
            alt.Tooltip("Value:Q", title="Worth", format="$.2f"),
            alt.Tooltip("Label:N", title="Share"),
        ]
    )
    labels = base.mark_text(align="left", dx=4).encode(text="Label:N")  # direct labels
    biggest = rows[0]
    st.altair_chart(
        bars + labels,
        alt=f"How the practice money is shared out. The biggest is {biggest['Company']} "
        f"at {biggest['Label']}.",
    )


def _market(market) -> None:
    st.subheader("Look up a price")
    ticker = st.selectbox(
        "Company",
        list(WATCHLIST),
        format_func=view.company_label,
        key="market_pick",
    )
    try:
        with st.spinner("Looking up the price..."):
            quote = market.quote(ticker)
            history = market.history(ticker, view.HISTORY_DAYS)
    except MarketDataError:
        st.warning("Penny could not find this price right now. Please try again later.")
        return

    st.metric(
        quote.name,
        dollars(quote.price_cents),
        view.change_words(quote),
        border=True,
    )
    rows = view.history_rows(history)
    st.altair_chart(
        alt.Chart(alt.Data(values=rows))
        .mark_line(point=False)
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("Price:Q", title="Price ($)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("Date:T"), alt.Tooltip("Price:Q", format="$.2f")],
        ),
        alt=f"{quote.name} share price over the last {len(rows)} trading days",
    )
    st.caption(md(f"{view.served_by({quote.source, history.source})} As of {quote.as_of:%B %d}."))
    st.caption("One day's move does not tell you much. Nobody knows what prices do next.")
