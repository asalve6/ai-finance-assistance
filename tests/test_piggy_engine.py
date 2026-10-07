import pytest

from penny.contracts import GameEngine, GameState, Level
from penny.engines.piggy import PiggyEngine

engine = PiggyEngine()


def _play_all_weeks(state: GameState, decision: dict) -> tuple[GameState, list]:
    facts = []
    while not state.finished:
        state, f = engine.submit(state, decision)
        facts.append(f)
    return state, facts


def test_follows_the_engine_contract():
    typed: GameEngine = engine  # fails type checking if the protocol is not met
    assert typed.game_type == "piggy"


@pytest.mark.parametrize("level", list(Level))
def test_start_depends_on_level(level):
    state = engine.start(level, seed=1)
    assert state.day == 1 and not state.finished
    assert state.data["saved_cents"] == 0
    assert state.data["event"]["price_cents"] <= state.data["allowance_cents"]


def test_same_seed_gives_same_game_and_other_seed_can_differ():
    a = engine.start(Level.SAVER, seed=42)
    b = engine.start(Level.SAVER, seed=42)
    assert a == b
    events = {engine.start(Level.SAVER, seed=s).data["event"]["name"] for s in range(30)}
    assert len(events) > 1


def test_saving_everything_and_resisting_earns_coins():
    state = engine.start(Level.STARTER, seed=1)
    _, facts = engine.submit(state, {"save_cents": 1000, "buy_temptation": False})
    assert facts.profit_cents == 1000
    assert facts.coins_earned == 100 + 20  # 1 coin per 10 cents, plus resisting bonus
    assert facts.outcome["resisted_temptation"] is True
    assert facts.xp_earned == 20


def test_buying_the_temptation_loses_the_resist_bonus():
    state = engine.start(Level.STARTER, seed=1)
    price = state.data["event"]["price_cents"]
    save = 1000 - price
    _, facts = engine.submit(state, {"save_cents": save, "buy_temptation": True})
    assert facts.coins_earned == save // 10
    assert facts.outcome["bought_temptation"] is True


def test_submit_does_not_mutate_the_input_state():
    state = engine.start(Level.STARTER, seed=3)
    snapshot = state.model_copy(deep=True)
    engine.submit(state, {"save_cents": 500})
    assert state == snapshot


def test_game_advances_then_finishes_on_the_last_week():
    state = engine.start(Level.STARTER, seed=1)
    final, facts = _play_all_weeks(state, {"save_cents": 1000, "buy_temptation": False})
    assert len(facts) == state.total_days == 4
    assert [f.day for f in facts] == [1, 2, 3, 4]
    assert [f.finished for f in facts] == [False, False, False, True]
    assert final.finished and final.data["event"] is None
    assert final.data["saved_cents"] == 4000


def test_goal_bonus_only_when_the_goal_is_reached_at_the_end():
    state = engine.start(Level.STARTER, seed=1)  # goal 3000
    _, rich = _play_all_weeks(state, {"save_cents": 1000, "buy_temptation": False})
    _, poor = _play_all_weeks(state, {"save_cents": 100, "buy_temptation": False})
    assert rich[-1].outcome["goal_reached"] is True
    assert rich[-1].coins_earned == 100 + 20 + 100
    assert poor[-1].outcome["goal_reached"] is False
    assert poor[-1].coins_earned == 10 + 20


@pytest.mark.parametrize(
    "decision",
    [
        {},
        {"save_cents": -1},
        {"save_cents": 1001},
        {"save_cents": 10.5},
        {"save_cents": True},
        {"save_cents": "500"},
    ],
)
def test_rejects_invalid_decisions(decision):
    state = engine.start(Level.STARTER, seed=1)
    with pytest.raises(ValueError):
        engine.submit(state, decision)


def test_cannot_buy_what_you_cannot_afford():
    state = engine.start(Level.STARTER, seed=1)
    with pytest.raises(ValueError, match="afford"):
        engine.submit(state, {"save_cents": 1000, "buy_temptation": True})


def test_cannot_play_after_the_game_is_finished():
    state = engine.start(Level.STARTER, seed=1)
    final, _ = _play_all_weeks(state, {"save_cents": 1000})
    with pytest.raises(ValueError, match="finished"):
        engine.submit(final, {"save_cents": 0})


def test_state_survives_a_json_round_trip_mid_game():
    state = engine.start(Level.BUILDER, seed=9)
    state, _ = engine.submit(state, {"save_cents": 800})
    restored = GameState.model_validate_json(state.model_dump_json())
    assert restored == state
    engine.submit(restored, {"save_cents": 800})
