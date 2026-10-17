"""The Goals tab: pick a goal, see how much to save each week, and a family challenge."""

from __future__ import annotations

import altair as alt
import streamlit as st

from penny.ui import goals
from penny.ui.session import Player
from penny.ui.text import dollars, md


def _on_goal_choice(player: Player) -> None:
    """Runs before the rerun, so the sidebar already shows the new goal."""
    choice = st.session_state["goal_choice"]
    if choice == goals.OWN_GOAL:
        st.session_state.setdefault("goal_own_name", goals.DEFAULT_OWN_NAME)
        st.session_state.setdefault("goal_own_price", 20.0)
        _on_own_goal(player)
    else:
        goals.choose_preset(player, choice)


def _on_own_goal(player: Player) -> None:
    goals.choose_own(player, st.session_state["goal_own_name"], st.session_state["goal_own_price"])


def render(player: Player) -> None:
    plan_column, family_column = st.columns([3, 2], gap="large")
    with plan_column:
        _planner(player)
    with family_column:
        _family_challenge()


def _planner(player: Player) -> None:
    st.subheader("My saving goal")
    choice = st.segmented_control(
        "What are you saving for?",
        goals.goal_options(),
        default=goals.current_option(player),
        required=True,
        format_func=md,
        wrap=True,  # four goals do not fit one row in this column; wrap instead of scrolling
        key="goal_choice",
        on_change=_on_goal_choice,
        args=(player,),
    )
    if choice == goals.OWN_GOAL:
        with st.container(horizontal=True):
            st.text_input(
                "Goal name", value=player.goal_name, max_chars=30, key="goal_own_name",
                on_change=_on_own_goal, args=(player,),
            )  # fmt: skip
            st.number_input(
                "Price in dollars", min_value=1.0, max_value=float(goals.MAX_OWN_PRICE_DOLLARS),
                value=player.goal_cents / 100, step=1.0, format="%.2f", key="goal_own_price",
                on_change=_on_own_goal, args=(player,),
            )  # fmt: skip

    weeks = st.slider(
        "Weeks to save", goals.MIN_WEEKS, goals.MAX_WEEKS, goals.DEFAULT_WEEKS, key="goal_weeks"
    )
    use_saved = False
    if player.saved_cents:
        use_saved = st.toggle(
            md(f"Count the {dollars(player.saved_cents)} I have saved in the games"),
            value=True,
            key="goal_use_saved",
        )
    rate = 0.0
    if st.toggle("Keep it in a savings account that pays interest", key="goal_interest"):
        rate = st.slider("Interest per year (%)", 0.5, 5.0, 3.0, 0.5, key="goal_rate")

    plan = goals.plan_for(player, weeks, use_saved, rate)
    with st.container(horizontal=True):
        st.metric("Save each week", dollars(plan.per_week_cents), border=True)
        st.metric("You put in", dollars(plan.deposited_cents), border=True)
        st.metric("Interest earned", dollars(plan.interest_cents), border=True)
    st.markdown(md(goals.summary(plan, player.goal_name)))
    st.caption("Worked out by Penny's goal planner, not guessed.")
    _chart(plan)


def _chart(plan) -> None:
    goal = plan.goal_cents / 100
    in_jar = alt.Tooltip("Balance:Q", title="In the jar", format="$.2f")
    bars = (
        alt.Chart(alt.Data(values=goals.chart_rows(plan)))
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("Week:O", title="Week"),
            y=alt.Y("Balance:Q", title="In the jar ($)"),
            tooltip=[alt.Tooltip("Week:O"), in_jar],
        )
    )
    goal_line = (
        alt.Chart(alt.Data(values=[{"Goal": goal}]))
        .mark_rule(strokeDash=[6, 4], color="#4b4f5c")
        .encode(y="Goal:Q", tooltip=[alt.Tooltip("Goal:Q", format="$.2f")])
    )
    st.altair_chart(
        bars + goal_line,
        alt=f"Money in the jar each week, reaching the {dollars(plan.goal_cents)} goal "
        f"in week {plan.weeks}",
    )


def _family_challenge() -> None:
    with st.container(border=True):
        st.subheader("Family challenge of the week")
        index = st.session_state.setdefault("family_prompt", 0)
        st.markdown(goals.FAMILY_PROMPTS[index])
        st.caption("Ask someone at home, listen to their answer, then share yours.")
        if st.button("Another question", icon=":material/refresh:", key="family_next"):
            st.session_state["family_prompt"] = goals.next_prompt(index)
            st.rerun()
