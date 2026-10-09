import pytest

from penny.contracts import Level
from penny.engines import lemonade, piggy
from penny.engines.goal import _simulate, plan_goal, weeks_needed
from penny.engines.lemonade import LemonadeEngine, simulate_day

# ------------------------------------------------------------------ weekly amount, no interest


def test_the_classic_case_60_dollars_in_8_weeks_is_7_50_a_week():
    plan = plan_goal(6000, 8)
    assert plan.per_week_cents == 750
    assert plan.deposited_cents == 6000 and plan.interest_cents == 0
    assert plan.balances_cents == [750, 1500, 2250, 3000, 3750, 4500, 5250, 6000]
    assert plan.already_reached is False


@pytest.mark.parametrize(
    ("goal", "weeks", "per_week"),
    [(4500, 7, 643), (100, 3, 34), (1, 1, 1), (12000, 16, 750), (999, 520, 2)],
)
def test_the_weekly_amount_rounds_up_so_the_goal_is_always_reached(goal, weeks, per_week):
    plan = plan_goal(goal, weeks)
    assert plan.per_week_cents == per_week
    assert plan.balances_cents[-1] >= goal
    assert (per_week - 1) * weeks < goal  # one cent less would fall short


def test_money_already_saved_lowers_the_weekly_amount():
    plan = plan_goal(6000, 8, saved_cents=2000)
    assert plan.per_week_cents == 500
    assert plan.balances_cents[0] == 2500 and plan.balances_cents[-1] == 6000
    assert plan.deposited_cents == 4000


@pytest.mark.parametrize("saved", [6000, 7500])
def test_a_goal_that_is_already_reached_needs_nothing_more(saved):
    plan = plan_goal(6000, 8, saved_cents=saved)
    assert plan.already_reached is True and plan.per_week_cents == 0
    assert plan.balances_cents == [saved] * 8


# ------------------------------------------------------------------ with interest


def test_interest_means_a_little_less_to_put_in():
    without = plan_goal(100_000, 104)
    with_interest = plan_goal(100_000, 104, annual_rate_pct=5)
    assert with_interest.per_week_cents < without.per_week_cents
    assert with_interest.interest_cents > 0
    assert with_interest.balances_cents[-1] >= 100_000
    assert (
        with_interest.deposited_cents + with_interest.interest_cents
        == (with_interest.balances_cents[-1])
    )


def test_the_interest_plan_is_the_smallest_amount_that_works():
    plan = plan_goal(100_000, 104, annual_rate_pct=5)
    one_less = _simulate(0, plan.per_week_cents - 1, 104, 5)[0][-1]
    assert one_less < 100_000 <= plan.balances_cents[-1]


def test_interest_is_added_weekly_and_rounded_down():
    # $1000 already saved at 5.2% a year is 0.1% a week: exactly $1.00 in week one.
    plan = plan_goal(200_000, 2, saved_cents=100_000, annual_rate_pct=5.2)
    first_week_interest = plan.balances_cents[0] - 100_000 - plan.per_week_cents
    assert first_week_interest == int((100_000 + plan.per_week_cents) * 0.001)


def test_on_a_small_short_goal_interest_barely_matters():
    # $60 in 8 weeks at 3% a year: 12 cents of interest, so one cent less per week is enough.
    plan = plan_goal(6000, 8, annual_rate_pct=3)
    assert (plan.per_week_cents, plan.interest_cents, plan.balances_cents[-1]) == (749, 12, 6004)


def test_a_zero_rate_is_the_same_as_no_interest():
    assert plan_goal(6000, 8, annual_rate_pct=0) == plan_goal(6000, 8)


def test_balances_never_go_down():
    balances = plan_goal(50_000, 60, saved_cents=1234, annual_rate_pct=4).balances_cents
    assert balances == sorted(balances) and len(balances) == 60


# ------------------------------------------------------------------ how long will it take


@pytest.mark.parametrize(
    ("goal", "per_week", "saved", "weeks"),
    [
        (6000, 750, 0, 8),
        (6000, 700, 0, 9),
        (6000, 500, 2000, 8),
        (6000, 1, 5999, 1),
        (6000, 500, 6000, 0),
    ],
)
def test_weeks_needed(goal, per_week, saved, weeks):
    assert weeks_needed(goal, per_week, saved) == weeks


def test_the_two_questions_agree_with_each_other():
    plan = plan_goal(4500, 7)
    assert weeks_needed(4500, plan.per_week_cents) == 7


# ------------------------------------------------------------------ bad input


@pytest.mark.parametrize(
    "kwargs",
    [
        {"goal_cents": 0, "weeks": 4},
        {"goal_cents": -5, "weeks": 4},
        {"goal_cents": 100, "weeks": 0},
        {"goal_cents": 100, "weeks": 521},
        {"goal_cents": 100, "weeks": 4, "saved_cents": -1},
        {"goal_cents": 100, "weeks": 4, "annual_rate_pct": -1},
        {"goal_cents": 100, "weeks": 4, "annual_rate_pct": 20.5},
    ],
)
def test_plan_goal_rejects_impossible_inputs(kwargs):
    with pytest.raises(ValueError):
        plan_goal(**kwargs)


@pytest.mark.parametrize("args", [(0, 100, 0), (100, 0, 0), (100, -5, 0), (100, 10, -1)])
def test_weeks_needed_rejects_impossible_inputs(args):
    with pytest.raises(ValueError):
        weeks_needed(*args)


# ------------------------------------------------------------------ lemonade "what if"


def test_simulate_day_matches_the_hand_calculation():
    day = simulate_day(Level.STARTER, "sunny", 75, 20)
    assert (day["demand"], day["cups_sold"], day["profit_cents"]) == (20, 20, 1100)
    assert (day["revenue_cents"], day["spend_cents"]) == (1500, 400)


def test_simulate_day_is_the_same_maths_as_the_real_game():
    engine = LemonadeEngine()
    for level in Level:
        state = engine.start(level, seed=1)  # day one is always sunny
        _, facts = engine.submit(state, {"price_cents": 95, "cups": 35})
        day = simulate_day(level, "sunny", 95, 35)
        assert day["profit_cents"] == facts.profit_cents
        assert {k: v for k, v in day.items() if k != "profit_cents"} == {
            k: v for k, v in facts.outcome.items() if k != "total_profit_cents"
        }


def test_rain_and_harder_levels_change_the_result():
    sunny = simulate_day(Level.STARTER, "sunny", 100, 30)
    rainy = simulate_day(Level.STARTER, "rainy", 100, 30)
    builder = simulate_day(Level.BUILDER, "sunny", 100, 30)
    assert rainy["demand"] < sunny["demand"] and rainy["profit_cents"] < 0
    assert builder["spend_cents"] > sunny["spend_cents"]


@pytest.mark.parametrize(
    ("weather", "price", "cups"),
    [("snowy", 75, 20), ("sunny", 10, 20), ("sunny", 75, 0), ("sunny", 75.0, 20)],
)
def test_simulate_day_rejects_choices_the_game_would_reject(weather, price, cups):
    with pytest.raises(ValueError):
        simulate_day(Level.STARTER, weather, price, cups)


# ------------------------------------------------------------------ rules summaries


def test_lemonade_rules_come_from_the_engines_own_numbers():
    rules = lemonade.rules(Level.SAVER)
    assert rules["cost_per_cup_cents"] == 25 and rules["days"] == 3
    assert rules["price_range_cents"] == [25, 150] and rules["cups_range"] == [1, 60]
    assert rules["customers_on_a_normal_price_day"] == {"sunny": 24, "cloudy": 16, "rainy": 8}
    assert "at least 5 per day" in rules["coins"]


@pytest.mark.parametrize(
    ("level", "goal", "allowance", "weeks"),
    [(Level.STARTER, 3000, 1000, 4), (Level.SAVER, 5000, 1200, 5), (Level.BUILDER, 7000, 1500, 6)],
)
def test_piggy_rules_come_from_the_engines_own_numbers(level, goal, allowance, weeks):
    rules = piggy.rules(level)
    assert (rules["goal_cents"], rules["allowance_cents_per_week"], rules["weeks"]) == (
        goal,
        allowance,
        weeks,
    )
    assert "20 for skipping the temptation" in rules["coins"]
    assert "100 for reaching the goal" in rules["coins"]
