"""The Play tab: the Piggy Bank and Lemonade Stand games."""

from __future__ import annotations

import streamlit as st

from penny.engines.lemonade import MAX_CUPS, MAX_PRICE_CENTS, MIN_CUPS, MIN_PRICE_CENTS
from penny.ui import games
from penny.ui.session import Player
from penny.ui.text import dollars, md, weeks

GAMES = ("Piggy Bank", "Lemonade Stand")
SKIP, BUY = "Skip it", "Buy it"


def render(player: Player) -> None:
    game = st.radio("Game", GAMES, horizontal=True, key="game")
    if game == GAMES[0]:
        _piggy(player)
    else:
        _lemonade(player)


# ------------------------------------------------------------------ piggy bank


def _piggy(player: Player) -> None:
    if player.piggy is None:
        games.start_piggy(player)
    state, data = player.piggy, player.piggy.data
    goal, saved = data["goal_cents"], data["saved_cents"]

    jar, turn = st.columns([1, 2])
    with jar:
        st.metric("In the jar", dollars(saved))
        st.progress(min(1.0, saved / goal), text=md(f"of your {dollars(goal)} goal"))
    with turn:
        if player.piggy_last is not None:
            _piggy_result(player)
        else:
            _piggy_decide(player, state.day, state.total_days, data)


def _piggy_decide(player: Player, week: int, total: int, data: dict) -> None:
    allowance, event = data["allowance_cents"], data["event"]
    st.subheader(f"Week {week} of {total}")
    st.write(
        md(
            f"You got your {dollars(allowance)} allowance. This week's temptation: "
            f"{event['name']} for {dollars(event['price_cents'])}."
        )
    )
    save = st.slider(
        "Put in the jar (dollars)", 0, allowance // 100, allowance // 200, key="piggy_save"
    )
    save_cents = save * 100
    affordable = games.can_afford_temptation(player, save_cents)
    choice = st.radio(
        "The temptation", (SKIP, BUY), horizontal=True, key="piggy_buy", disabled=not affordable
    )
    left = dollars(allowance - save_cents)
    if affordable:
        st.caption(md(f"You have {left} left after saving, so you can afford it."))
    else:
        st.caption(
            md(f"You only have {left} left after saving, so you cannot afford it this week.")
        )
    if st.button("Finish the week", type="primary", key="piggy_finish"):
        games.play_piggy_week(player, save_cents, buy=affordable and choice == BUY)
        st.rerun()


def _piggy_result(player: Player) -> None:
    facts = player.piggy_last
    st.subheader(f"Week {facts.day} of {player.piggy.total_days}: done")
    with st.chat_message("assistant"):
        st.markdown(md(games.piggy_feedback(facts)))
    st.caption(
        f"+{facts.coins_earned} coins, +{facts.xp_earned} XP. Drop streak: {weeks(player.streak)}."
    )
    label = "Play again" if facts.finished else "Next week"
    if st.button(label, type="primary", key="piggy_next"):
        games.next_piggy_week(player)
        st.rerun()


# ------------------------------------------------------------------ lemonade stand


def _lemonade(player: Player) -> None:
    if player.lemonade is None:
        games.start_lemonade(player)
    state = player.lemonade
    cost = state.data["cost_per_cup_cents"]

    turn, chart = st.columns([3, 2])
    with turn:
        if player.lemonade_last is not None:
            _lemonade_result(player, cost)
        else:
            _lemonade_decide(player, state.day, state.total_days, state.data["weather"], cost)
    with chart:
        st.write("**Profit by day**")
        if player.lemonade_profits:
            days = [f"Day {n}" for n in range(1, len(player.lemonade_profits) + 1)]
            profit = [cents / 100 for cents in player.lemonade_profits]
            st.bar_chart({"Day": days, "Profit ($)": profit}, x="Day", y="Profit ($)")
            st.caption("Bars above zero are profit. Bars below zero are a loss.")
        else:
            st.caption("Play a day to see your profit here.")


def _lemonade_decide(player: Player, day: int, total: int, weather: dict, cost: int) -> None:
    st.subheader(f"Day {day} of {total}: {weather['label']}")
    st.write(md(f"Each cup costs you {dollars(cost)} to make. Pick a price and how many cups."))
    price = st.select_slider(
        "Price per cup",
        options=list(range(MIN_PRICE_CENTS, MAX_PRICE_CENTS + 1, 5)),
        value=75,
        format_func=lambda cents: md(dollars(cents)),
        key="lemon_price",
    )
    cups = st.slider("Cups to make", MIN_CUPS, MAX_CUPS, 20, key="lemon_cups")
    st.caption(md(f"Supplies will cost {dollars(cups * cost)}."))
    if st.button("Open the stand", type="primary", key="lemon_open"):
        games.play_lemonade_day(player, price, cups)
        st.rerun()


def _lemonade_result(player: Player, cost: int) -> None:
    facts = player.lemonade_last
    out = facts.outcome
    st.subheader(f"Day {facts.day} of {player.lemonade.total_days}: {out['weather_label']}")
    profit, sold, money_in = st.columns(3)
    profit.metric("Profit", dollars(facts.profit_cents))
    sold.metric("Sold", f"{out['cups_sold']} of {out['cups_made']}")
    money_in.metric("Money in", dollars(out["revenue_cents"]))
    with st.chat_message("assistant"):
        st.markdown(md(games.lemonade_feedback(facts, cost)))
    st.caption(f"+{facts.coins_earned} coins, +{facts.xp_earned} XP.")
    label = "Play again" if facts.finished else "Next day"
    if st.button(label, type="primary", key="lemon_next"):
        games.next_lemonade_day(player)
        st.rerun()
