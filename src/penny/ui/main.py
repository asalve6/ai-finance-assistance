"""The app's top level: page setup, sidebar, then the setup screen or the four tabs."""

from __future__ import annotations

import streamlit as st

from penny.config import load_env
from penny.ui import APP_NAME, chat, setup, sidebar
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

    chat_tab, play_tab, portfolio_tab, goals_tab = st.tabs(TABS)
    with chat_tab:
        chat.render(player)
    with play_tab:
        st.info("The Piggy Bank and Lemonade Stand games arrive in the next step.")
    with portfolio_tab:
        st.info("Practice portfolio and market quotes are coming soon.")
    with goals_tab:
        st.info("The saving goal planner is coming soon.")
