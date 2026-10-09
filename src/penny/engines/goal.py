"""Goal planner: how much to save each week, or how many weeks it will take.

Pure integer maths in cents, so there are no rounding surprises. With interest, the plan is found
by simulating week by week (interest is added once a week and rounded down), so the weekly amount
it returns is guaranteed to reach the goal under exactly the rule it describes.
"""

from __future__ import annotations

from pydantic import BaseModel

MAX_WEEKS = 520  # ten years
MAX_RATE_PCT = 20.0
WEEKS_PER_YEAR = 52


class GoalPlan(BaseModel):
    goal_cents: int
    weeks: int
    saved_cents: int  # what the saver already had
    annual_rate_pct: float
    per_week_cents: int
    deposited_cents: int  # total put in over the plan, not counting what was already saved
    interest_cents: int  # earned along the way
    balances_cents: list[int]  # balance at the end of each week
    already_reached: bool


def _check(goal_cents: int, saved_cents: int) -> None:
    if goal_cents <= 0:
        raise ValueError("goal_cents must be more than 0")
    if saved_cents < 0:
        raise ValueError("saved_cents cannot be negative")


def _simulate(
    start: int, per_week: int, weeks: int, annual_rate_pct: float
) -> tuple[list[int], int]:
    """Deposit at the start of each week, then add that week's interest, rounded down."""
    weekly_rate = annual_rate_pct / 100 / WEEKS_PER_YEAR
    balance, interest_total, balances = start, 0, []
    for _ in range(weeks):
        balance += per_week
        interest = int(balance * weekly_rate)
        balance += interest
        interest_total += interest
        balances.append(balance)
    return balances, interest_total


def plan_goal(
    goal_cents: int, weeks: int, saved_cents: int = 0, annual_rate_pct: float = 0.0
) -> GoalPlan:
    """The smallest whole-cent weekly amount that reaches the goal in `weeks` weeks."""
    _check(goal_cents, saved_cents)
    if not 1 <= weeks <= MAX_WEEKS:
        raise ValueError(f"weeks must be from 1 to {MAX_WEEKS}")
    if not 0 <= annual_rate_pct <= MAX_RATE_PCT:
        raise ValueError(f"annual_rate_pct must be from 0 to {MAX_RATE_PCT:g}")

    remaining = goal_cents - saved_cents
    if remaining <= 0:
        balances, interest = _simulate(saved_cents, 0, weeks, annual_rate_pct)
        per_week = 0
    else:
        # Without interest the answer is a simple ceiling. With interest it can only be lower, so
        # search downward from there for the smallest amount that still gets to the goal.
        low, high = 0, -(-remaining // weeks)
        while low < high:
            middle = (low + high) // 2
            if _simulate(saved_cents, middle, weeks, annual_rate_pct)[0][-1] >= goal_cents:
                high = middle
            else:
                low = middle + 1
        per_week = low
        balances, interest = _simulate(saved_cents, per_week, weeks, annual_rate_pct)

    return GoalPlan(
        goal_cents=goal_cents,
        weeks=weeks,
        saved_cents=saved_cents,
        annual_rate_pct=annual_rate_pct,
        per_week_cents=per_week,
        deposited_cents=per_week * weeks,
        interest_cents=interest,
        balances_cents=balances,
        already_reached=remaining <= 0,
    )


def weeks_needed(goal_cents: int, per_week_cents: int, saved_cents: int = 0) -> int:
    """How many weeks of saving `per_week_cents` (no interest) it takes to reach the goal."""
    _check(goal_cents, saved_cents)
    if per_week_cents <= 0:
        raise ValueError("per_week_cents must be more than 0")
    remaining = goal_cents - saved_cents
    return 0 if remaining <= 0 else -(-remaining // per_week_cents)
