"""First-run screen: a nickname and three questions that set the reading level."""

from __future__ import annotations

import streamlit as st

from penny.contracts import Level
from penny.ui import APP_NAME
from penny.ui.quiz import QUESTIONS, level_for
from penny.ui.session import Player
from penny.ui.text import md


def render(player: Player) -> None:
    st.title(f"Welcome to {APP_NAME}")
    st.write(
        "Three quick questions help Penny pick the right words for you. There are no wrong answers."
    )
    with st.form("setup"):
        nickname = st.text_input(
            "Your nickname", placeholder="A nickname, not your real name", max_chars=20
        )
        picks = [
            st.radio(md(q.text), q.options, index=None, key=f"quiz_{i}")
            for i, q in enumerate(QUESTIONS)
        ]
        start = st.form_submit_button("Start learning", type="primary")
    skip = st.button("Skip, start as a Starter")

    if start:
        answers = [
            q.options.index(pick) if pick is not None else None
            for q, pick in zip(QUESTIONS, picks, strict=True)
        ]
        _begin(player, nickname, level_for(answers))
    elif skip:
        _begin(player, "", Level.STARTER)


def _begin(player: Player, nickname: str, level: Level) -> None:
    player.nickname = nickname.strip()
    player.level = level
    player.started = True
    st.rerun()
