"""The app's top level: page setup, sidebar, then the setup screen or the four tabs."""

from __future__ import annotations

import streamlit as st

from penny.config import load_env
from penny.ui import APP_NAME, chat, goal_tab, play, portfolio_tab, setup, sidebar
from penny.ui.session import get_player

TABS = ("Chat", "Play", "Portfolio and Markets", "Goals")


def run() -> None:
    load_env()
    st.set_page_config(page_title=APP_NAME, page_icon=":material/savings:", layout="wide")
    player = get_player(st.session_state)
    sidebar.render(player)
    if not player.started:
        setup.render(player)
        return

    # Rerun on a tab change, so the Portfolio tab only looks up prices while it is open.
    chat_t, play_t, portfolio_t, goals_t = st.tabs(TABS, key="tab", on_change="rerun")
    with chat_t:
        chat.render(player)
    with play_t:
        play.render(player)
    with portfolio_t:
        if portfolio_t.open:
            portfolio_tab.render(player)
        else:
            portfolio_tab.forget()
    with goals_t:
        goal_tab.render(player)
