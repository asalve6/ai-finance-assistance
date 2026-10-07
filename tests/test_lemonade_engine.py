import pytest

from penny.contracts import GameEngine, GameState, Level
from penny.engines.lemonade import LemonadeEngine, demand_for

engine = LemonadeEngine()


def _play(state: GameState, decision: dict) -> tuple[GameState, list]:
    facts = []
    while not state.finished:
        state, f = engine.submit(state, decision)
        facts.append(f)
    return state, facts


def test_follows_the_engine_contract():
    typed: GameEngine = engine
    assert typed.game_type == "lemonade"


def test_day_one_is_always_sunny():
    for seed in range(20):
        assert engine.start(Level.STARTER, seed).data["weather"]["kind"] == "sunny"


def test_known_good_day_matches_the_hand_calculation():
    # sunny base 24, price 75: 24 * 85 / 100 = 20.4 -> 20 customers
    state = engine.start(Level.STARTER, seed=1)
    _, facts = engine.submit(state, {"price_cents": 75, "cups": 20})
    out = facts.outcome
    assert (out["demand"], out["cups_sold"], out["cups_unsold"]) == (20, 20, 0)
    assert out["revenue_cents"] == 1500
    assert out["spend_cents"] == 400  # 20 cups * 20 cents
    assert facts.profit_cents == 1100
    assert facts.coins_earned == 110
    assert out["sold_out"] is False and out["customers_missed"] == 0


def test_selling_out_reports_missed_customers():
    state = engine.start(Level.STARTER, seed=1)
    _, facts = engine.submit(state, {"price_cents": 75, "cups": 10})
    assert facts.outcome["sold_out"] is True
    assert facts.outcome["customers_missed"] == 10
    assert facts.outcome["cups_sold"] == 10


def test_over_making_cups_leaves_unsold_cups_and_costs_money():
    state = engine.start(Level.STARTER, seed=1)
    _, facts = engine.submit(state, {"price_cents": 75, "cups": 40})
    assert facts.outcome["cups_unsold"] == 20
    assert facts.profit_cents == 20 * 75 - 40 * 20  # 700


def test_a_bad_day_is_a_loss_but_still_earns_the_minimum_coins():
    state = engine.start(Level.STARTER, seed=1)
    _, facts = engine.submit(state, {"price_cents": 150, "cups": 60})
    assert facts.profit_cents < 0
    assert facts.coins_earned == 5


def test_higher_prices_never_increase_demand():
    for base in (8, 16, 24):
        demands = [demand_for(base, p) for p in range(25, 151, 5)]
        assert demands == sorted(demands, reverse=True)
        assert demands[-1] >= 0


def test_demand_rounds_half_up_not_to_even():
    # 24 * (160 - 77) = 1992 -> 19.92 -> 20; and exactly x.5 rounds up: 10 * 65 / 100 = 6.5 -> 7
    assert demand_for(24, 77) == 20
    assert demand_for(10, 95) == 7


def test_harder_levels_cost_more_per_cup():
    costs = [engine.start(lvl, 1).data["cost_per_cup_cents"] for lvl in Level]
    assert costs == [20, 25, 30]


def test_same_seed_same_weather_and_other_seeds_vary():
    def forecast(seed: int) -> list[str]:
        state = engine.start(Level.SAVER, seed)
        kinds = [state.data["weather"]["kind"]]
        while not state.finished:
            state, _ = engine.submit(state, {"price_cents": 75, "cups": 20})
            if state.data["weather"]:
                kinds.append(state.data["weather"]["kind"])
        return kinds

    assert forecast(5) == forecast(5)
    assert len({tuple(forecast(s)) for s in range(30)}) > 1


def test_game_runs_three_days_then_finishes_and_totals_the_profit():
    state = engine.start(Level.STARTER, seed=2)
    final, facts = _play(state, {"price_cents": 75, "cups": 15})
    assert [f.day for f in facts] == [1, 2, 3]
    assert [f.finished for f in facts] == [False, False, True]
    assert final.finished and final.data["weather"] is None
    assert final.data["total_profit_cents"] == sum(f.profit_cents for f in facts)
    assert facts[-1].outcome["total_profit_cents"] == final.data["total_profit_cents"]


def test_submit_does_not_mutate_the_input_state():
    state = engine.start(Level.STARTER, seed=3)
    snapshot = state.model_copy(deep=True)
    engine.submit(state, {"price_cents": 75, "cups": 20})
    assert state == snapshot


@pytest.mark.parametrize(
    "decision",
    [
        {},
        {"price_cents": 75},
        {"cups": 20},
        {"price_cents": 24, "cups": 20},
        {"price_cents": 151, "cups": 20},
        {"price_cents": 75, "cups": 0},
        {"price_cents": 75, "cups": 61},
        {"price_cents": 0.75, "cups": 20},
        {"price_cents": "75", "cups": 20},
        {"price_cents": True, "cups": 20},
    ],
)
def test_rejects_invalid_decisions(decision):
    with pytest.raises(ValueError):
        engine.submit(engine.start(Level.STARTER, 1), decision)


def test_cannot_play_after_the_game_is_finished():
    final, _ = _play(engine.start(Level.STARTER, 1), {"price_cents": 75, "cups": 20})
    with pytest.raises(ValueError, match="finished"):
        engine.submit(final, {"price_cents": 75, "cups": 20})


def test_state_survives_a_json_round_trip_mid_game():
    state, _ = engine.submit(engine.start(Level.BUILDER, 9), {"price_cents": 75, "cups": 20})
    restored = GameState.model_validate_json(state.model_dump_json())
    assert restored == state
    engine.submit(restored, {"price_cents": 75, "cups": 20})
