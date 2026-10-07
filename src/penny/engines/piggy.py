"""Piggy Bank engine: save toward a goal while a weekly temptation shows up.

Each week the kid gets an allowance and sees one temptation. They decide how much to save and
whether to buy the temptation with the rest. Money is integer cents. Temptations come from a
seeded generator, so a given (level, seed) always plays out the same way.

Decision: {"save_cents": int, "buy_temptation": bool}
"""

from __future__ import annotations

import random
from typing import Any

from penny.contracts import GameFacts, GameState, GameType, Level

XP_PER_WEEK = 20
COINS_PER_10_CENTS_SAVED = 1
COINS_FOR_RESISTING = 20
COINS_FOR_REACHING_GOAL = 100

_SETTINGS: dict[Level, dict[str, int]] = {
    Level.STARTER: {"goal_cents": 3000, "allowance_cents": 1000, "weeks": 4},
    Level.SAVER: {"goal_cents": 5000, "allowance_cents": 1200, "weeks": 5},
    Level.BUILDER: {"goal_cents": 7000, "allowance_cents": 1500, "weeks": 6},
}

_TEMPTATIONS: list[tuple[str, int]] = [
    ("Arcade night", 800),
    ("Bubble tea with friends", 500),
    ("New phone case", 1200),
    ("Birthday gift for a friend", 700),
    ("Flash sale on sneakers", 1500),
]


def _event_for(seed: int, day: int, allowance_cents: int) -> dict[str, Any]:
    name, price = random.Random(seed * 1000 + day).choice(_TEMPTATIONS)
    return {"name": name, "price_cents": min(price, allowance_cents)}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class PiggyEngine:
    game_type = GameType.PIGGY

    def start(self, level: Level, seed: int) -> GameState:
        cfg = _SETTINGS[level]
        return GameState(
            game_type=self.game_type,
            seed=seed,
            day=1,
            total_days=cfg["weeks"],
            data={
                "level": level.value,
                "goal_cents": cfg["goal_cents"],
                "allowance_cents": cfg["allowance_cents"],
                "saved_cents": 0,
                "event": _event_for(seed, 1, cfg["allowance_cents"]),
            },
        )

    def submit(self, state: GameState, decision: dict[str, Any]) -> tuple[GameState, GameFacts]:
        if state.finished:
            raise ValueError("game is already finished")

        data = state.data
        allowance = data["allowance_cents"]
        event = data["event"]
        save = decision.get("save_cents")
        buy = bool(decision.get("buy_temptation", False))

        if not _is_int(save) or not 0 <= save <= allowance:
            raise ValueError(f"save_cents must be a whole number from 0 to {allowance}")
        if buy and event["price_cents"] > allowance - save:
            raise ValueError("cannot afford the temptation after saving that much")

        saved_total = data["saved_cents"] + save
        finished = state.day >= state.total_days
        goal_reached = saved_total >= data["goal_cents"]

        coins = save // 10 * COINS_PER_10_CENTS_SAVED
        if not buy:
            coins += COINS_FOR_RESISTING
        if finished and goal_reached:
            coins += COINS_FOR_REACHING_GOAL

        new_state = state.model_copy(deep=True)
        new_state.data["saved_cents"] = saved_total
        if finished:
            new_state.finished = True
            new_state.data["event"] = None
        else:
            new_state.day = state.day + 1
            new_state.data["event"] = _event_for(state.seed, new_state.day, allowance)

        facts = GameFacts(
            day=state.day,
            decision={"save_cents": save, "buy_temptation": buy},
            outcome={
                "saved_this_week_cents": save,
                "saved_total_cents": saved_total,
                "goal_cents": data["goal_cents"],
                "goal_reached": goal_reached,
                "temptation": event,
                "bought_temptation": buy,
                "resisted_temptation": not buy,
            },
            profit_cents=save,
            coins_earned=coins,
            xp_earned=XP_PER_WEEK,
            finished=finished,
        )
        return new_state, facts
