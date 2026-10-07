"""Lemonade Stand engine: pick a price and how many cups to make, then see what sells.

Three days. Each day has seeded weather that sets how many customers show up. Demand falls as
the price rises. Money is integer cents, and demand uses integer maths, so there are no float
rounding surprises.

    demand = base_demand * (160 - price_cents) / 100, rounded half up, never below 0
    sold   = min(cups, demand)
    profit = sold * price - cups * cost_per_cup

Decision: {"price_cents": int, "cups": int}
"""

from __future__ import annotations

import random
from typing import Any

from penny.contracts import GameFacts, GameState, GameType, Level

TOTAL_DAYS = 3
MIN_PRICE_CENTS, MAX_PRICE_CENTS = 25, 150
MIN_CUPS, MAX_CUPS = 1, 60
MIN_COINS_PER_DAY = 5
XP_PER_DAY = 25

_COST_PER_CUP_CENTS: dict[Level, int] = {Level.STARTER: 20, Level.SAVER: 25, Level.BUILDER: 30}

_WEATHER: dict[str, dict[str, Any]] = {
    "sunny": {"label": "Sunny and hot", "base_demand": 24},
    "cloudy": {"label": "Cloudy", "base_demand": 16},
    "rainy": {"label": "Rainy", "base_demand": 8},
}
_WEATHER_WEIGHTS = {"sunny": 4, "cloudy": 4, "rainy": 2}


def _weather_for(seed: int, day: int) -> dict[str, Any]:
    """Day 1 is always sunny, as a gentle start. Later days are seeded."""
    kind = "sunny"
    if day > 1:
        rng = random.Random(seed * 1000 + day)
        kind = rng.choices(list(_WEATHER_WEIGHTS), weights=list(_WEATHER_WEIGHTS.values()))[0]
    return {"kind": kind, **_WEATHER[kind]}


def demand_for(base_demand: int, price_cents: int) -> int:
    """Customers who would buy at this price. Integer maths, rounded half up."""
    return max(0, (base_demand * (160 - price_cents) + 50) // 100)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class LemonadeEngine:
    game_type = GameType.LEMONADE

    def start(self, level: Level, seed: int) -> GameState:
        return GameState(
            game_type=self.game_type,
            seed=seed,
            day=1,
            total_days=TOTAL_DAYS,
            data={
                "level": level.value,
                "cost_per_cup_cents": _COST_PER_CUP_CENTS[level],
                "total_profit_cents": 0,
                "weather": _weather_for(seed, 1),
            },
        )

    def submit(self, state: GameState, decision: dict[str, Any]) -> tuple[GameState, GameFacts]:
        if state.finished:
            raise ValueError("game is already finished")

        price = decision.get("price_cents")
        cups = decision.get("cups")
        if not _is_int(price) or not MIN_PRICE_CENTS <= price <= MAX_PRICE_CENTS:
            raise ValueError(
                f"price_cents must be a whole number from {MIN_PRICE_CENTS} to {MAX_PRICE_CENTS}"
            )
        if not _is_int(cups) or not MIN_CUPS <= cups <= MAX_CUPS:
            raise ValueError(f"cups must be a whole number from {MIN_CUPS} to {MAX_CUPS}")

        data = state.data
        weather = data["weather"]
        cost = data["cost_per_cup_cents"]

        demand = demand_for(weather["base_demand"], price)
        sold = min(cups, demand)
        revenue = sold * price
        spend = cups * cost
        profit = revenue - spend
        finished = state.day >= state.total_days

        new_state = state.model_copy(deep=True)
        new_state.data["total_profit_cents"] = data["total_profit_cents"] + profit
        if finished:
            new_state.finished = True
            new_state.data["weather"] = None
        else:
            new_state.day = state.day + 1
            new_state.data["weather"] = _weather_for(state.seed, new_state.day)

        facts = GameFacts(
            day=state.day,
            decision={"price_cents": price, "cups": cups},
            outcome={
                "weather": weather["kind"],
                "weather_label": weather["label"],
                "demand": demand,
                "cups_made": cups,
                "cups_sold": sold,
                "cups_unsold": cups - sold,
                "customers_missed": max(0, demand - cups),
                "sold_out": cups < demand,
                "revenue_cents": revenue,
                "spend_cents": spend,
                "total_profit_cents": new_state.data["total_profit_cents"],
            },
            profit_cents=profit,
            coins_earned=max(MIN_COINS_PER_DAY, profit // 10),
            xp_earned=XP_PER_DAY,
            finished=finished,
        )
        return new_state, facts
