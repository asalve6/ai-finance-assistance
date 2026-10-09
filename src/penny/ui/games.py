"""Game actions for the Play tab: run the engines and keep the player's rewards up to date.

Pure functions over `Player`, so every rule here is tested without Streamlit. The feedback is
templated from the engine's facts (no model call), so the games are instant and work offline.
"""

from __future__ import annotations

import random

from penny.contracts import GameFacts
from penny.engines.lemonade import LemonadeEngine
from penny.engines.piggy import PiggyEngine
from penny.ui.session import Player
from penny.ui.text import dollars

_piggy = PiggyEngine()
_lemonade = LemonadeEngine()


def new_seed() -> int:
    return random.SystemRandom().randrange(1_000_000)


# ------------------------------------------------------------------ piggy bank


def start_piggy(player: Player, seed: int | None = None) -> None:
    player.piggy = _piggy.start(player.level, new_seed() if seed is None else seed)
    player.piggy_last = None


def can_afford_temptation(player: Player, save_cents: int) -> bool:
    data = player.piggy.data
    return data["event"]["price_cents"] <= data["allowance_cents"] - save_cents


def play_piggy_week(player: Player, save_cents: int, buy: bool) -> GameFacts:
    state, facts = _piggy.submit(player.piggy, {"save_cents": save_cents, "buy_temptation": buy})
    player.piggy, player.piggy_last = state, facts
    player.coins += facts.coins_earned
    player.xp += facts.xp_earned
    player.streak = player.streak + 1 if save_cents > 0 else 0
    player.saved_cents += save_cents
    return facts


def next_piggy_week(player: Player) -> None:
    """Leave the result screen. After the last week this starts a new game."""
    if player.piggy.finished:
        start_piggy(player)
    player.piggy_last = None


def piggy_feedback(facts: GameFacts) -> str:
    out = facts.outcome
    saved, name = out["saved_this_week_cents"], out["temptation"]["name"]
    name = name[0].lower() + name[1:]
    if saved == 0:
        text = "No drops in the jar this week. That is okay. What could you save next week?"
    elif out["bought_temptation"]:
        price = dollars(out["temptation"]["price_cents"])
        text = (
            f"You saved {dollars(saved)} and bought {name} for {price}. "
            "Both are fine when you choose them on purpose."
        )
    else:
        text = f"You saved {dollars(saved)} and skipped {name}. More drops in your jar."
    if facts.finished:
        goal, total = dollars(out["goal_cents"]), dollars(out["saved_total_cents"])
        if out["goal_reached"]:
            text += f" You reached your {goal} goal. Little drops filled the jar."
        else:
            text += f" You finished with {total} of {goal}. What would you change next time?"
    return text


# ------------------------------------------------------------------ lemonade stand


def start_lemonade(player: Player, seed: int | None = None) -> None:
    player.lemonade = _lemonade.start(player.level, new_seed() if seed is None else seed)
    player.lemonade_last = None
    player.lemonade_profits = []


def play_lemonade_day(player: Player, price_cents: int, cups: int) -> GameFacts:
    state, facts = _lemonade.submit(player.lemonade, {"price_cents": price_cents, "cups": cups})
    player.lemonade, player.lemonade_last = state, facts
    player.lemonade_profits = [*player.lemonade_profits, facts.profit_cents]
    player.coins += facts.coins_earned
    player.xp += facts.xp_earned
    player.saved_cents += max(0, facts.profit_cents)  # a loss never takes from the jar
    return facts


def next_lemonade_day(player: Player) -> None:
    if player.lemonade.finished:
        start_lemonade(player)
    player.lemonade_last = None


def lemonade_feedback(facts: GameFacts, cost_per_cup_cents: int) -> str:
    out = facts.outcome
    if out["customers_missed"] > 0:
        text = (
            f"You sold out, and about {out['customers_missed']} more people wanted a cup. "
            "Making a few more could earn you extra."
        )
    elif out["cups_unsold"] > 0:
        text = (
            f"{out['cups_unsold']} cups went unsold, and each one cost you "
            f"{dollars(cost_per_cup_cents)}. Making fewer keeps more of your money."
        )
    else:
        text = "You made exactly as many cups as people wanted. That is hard to do."
    if facts.profit_cents < 0:
        text += " You lost money today, and that is useful to learn from."
    else:
        text += f" You kept {dollars(facts.profit_cents)} as profit."
    if facts.finished:
        text += (
            f" That was the last day. Your total profit was {dollars(out['total_profit_cents'])}."
        )
    return text
