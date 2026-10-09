"""The sidebar: who is playing, their level, coins, streak, XP and goal."""

from __future__ import annotations

import streamlit as st

from penny.ui import APP_NAME, TAGLINE
from penny.ui.session import XP_PER_LEVEL, Player, reset_player
from penny.ui.text import dollars, md, weeks


def render(player: Player) -> None:
    with st.sidebar:
        st.title(APP_NAME)
        st.caption(f"Hi, {player.display_name}. {TAGLINE}")
        st.metric("Level", player.level.value.title())
        coins, streak = st.columns(2)
        coins.metric("Coins", player.coins)
        streak.metric("Drop streak", weeks(player.streak))
        st.progress(
            player.xp_in_level / XP_PER_LEVEL,
            text=f"XP to next level: {player.xp_in_level} of {XP_PER_LEVEL}",
        )
        goal = f"{dollars(player.saved_cents)} of {dollars(player.goal_cents)}"
        st.progress(player.goal_progress, text=md(f"Goal: {player.goal_name}, {goal}"))
        st.caption("Runs on this computer only. Penny stores a nickname, never a real name.")
        if player.started and st.button("Restart setup"):
            reset_player(st.session_state)
            st.rerun()
