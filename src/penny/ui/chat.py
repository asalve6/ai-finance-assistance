"""The Chat tab: ask Penny, see the answer, its sources, and how it was produced."""

from __future__ import annotations

import uuid

import streamlit as st

from penny.graph.stubs import SAFE_FALLBACK
from penny.ui.backend import Backend, load_backend
from penny.ui.chat_model import GREETING, SUGGESTIONS, ChatTurn, build_turn
from penny.ui.chat_model import citation_line as source_line
from penny.ui.session import Player
from penny.ui.text import md


@st.cache_resource(show_spinner=False)
def _shared_backend() -> Backend:
    return load_backend()


def get_backend() -> Backend:
    """Tests put their own backend in the session. The app shares one across sessions."""
    return st.session_state.get("backend") or _shared_backend()


def ask(backend: Backend, player: Player, question: str, session_id: str) -> ChatTurn:
    try:
        result = backend.graph.ask(question, session_id=session_id, kid=player.kid())
    except Exception as exc:  # the chat must never crash on a child
        return ChatTurn(
            question=question,
            reply=SAFE_FALLBACK,
            caption=f"Something went wrong ({type(exc).__name__}), so Penny gave a safe reply.",
        )
    return build_turn(question, result, backend.sink.for_trace(result.trace_id))


def _show(turn: ChatTurn) -> None:
    with st.chat_message("user"):
        st.markdown(md(turn.question))
    with st.chat_message("assistant"):
        st.markdown(md(turn.reply))
        st.caption(turn.caption)
        if turn.citations:
            with st.expander(f"Sources ({len(turn.citations)})"):
                for citation in turn.citations:
                    st.markdown(source_line(citation))
        if turn.trace:
            with st.expander("How Penny answered"):
                st.table([row.model_dump() for row in turn.trace])


def render(player: Player) -> None:
    backend = get_backend()
    if not backend.live:
        st.info(
            f"Offline demo: Penny gives placeholder answers because {backend.note}. "
            "The games work as normal."
        )
    turns: list[ChatTurn] = st.session_state.setdefault("chat", [])
    session_id: str = st.session_state.setdefault("session_id", uuid.uuid4().hex)

    with st.chat_message("assistant"):
        st.markdown(GREETING)
    for turn in turns:
        _show(turn)

    picked = None
    if turns and turns[-1].also_ask:  # the other part of a mixed question
        also = turns[-1].also_ask
        if st.button(md(f"Also ask: {also}"), icon=":material/forum:", key="also_ask"):
            picked = also

    st.caption("Try asking:")
    columns = st.columns(2)  # two per row, so the full question fits on the button
    for i, suggestion in enumerate(SUGGESTIONS):
        if columns[i % 2].button(md(suggestion), key=f"suggest_{i}", width="stretch"):
            picked = suggestion
    typed = st.chat_input("Ask Penny a money question")

    question = (typed or picked or "").strip()
    if question:
        with st.spinner("Penny is thinking..."):
            turns.append(ask(backend, player, question, session_id))
        st.rerun()
