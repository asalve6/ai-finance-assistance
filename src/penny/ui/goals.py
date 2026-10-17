"""The Goals tab's logic: choosing and planning a goal, and the family challenge."""

from __future__ import annotations

from penny.engines.goal import GoalPlan, plan_goal
from penny.ui.session import Player
from penny.ui.text import dollars

PRESETS: tuple[tuple[str, int], ...] = (("Game", 6000), ("Bike", 12000), ("Concert ticket", 4500))
OWN_GOAL = "My own goal"
MIN_WEEKS, MAX_WEEKS, DEFAULT_WEEKS = 1, 52, 8
MAX_OWN_PRICE_DOLLARS = 1000

# The conversation starters from the "Money talks at home" article.
FAMILY_PROMPTS = (
    "How do you decide what is a need and what is a want?",
    "What is something our family is saving for together?",
    "What is one money lesson you learned when you were young?",
    "What is a good way to share or give to others?",
)


def preset_label(name: str, cents: int) -> str:
    return f"{name} {dollars(cents)}"


def goal_options() -> list[str]:
    return [preset_label(name, cents) for name, cents in PRESETS] + [OWN_GOAL]


def current_option(player: Player) -> str:
    """The option that matches the player's goal, or "My own goal" for anything else."""
    for name, cents in PRESETS:
        if (player.goal_name, player.goal_cents) == (name, cents):
            return preset_label(name, cents)
    return OWN_GOAL


def choose_preset(player: Player, label: str) -> None:
    for name, cents in PRESETS:
        if preset_label(name, cents) == label:
            player.goal_name, player.goal_cents = name, cents
            return
    raise ValueError(f"not a preset goal: {label!r}")


def choose_own(player: Player, name: str, price_dollars: float) -> None:
    """A goal the child names. Whole cents, at least one dollar, and a sensible upper limit."""
    cents = round(price_dollars * 100)
    if not 100 <= cents <= MAX_OWN_PRICE_DOLLARS * 100:
        raise ValueError(f"the price must be from $1 to ${MAX_OWN_PRICE_DOLLARS}")
    player.goal_name = name.strip() or DEFAULT_OWN_NAME
    player.goal_cents = cents


def plan_for(player: Player, weeks: int, use_saved: bool, yearly_rate_pct: float) -> GoalPlan:
    saved = player.saved_cents if use_saved else 0
    return plan_goal(player.goal_cents, weeks, saved, yearly_rate_pct)


DEFAULT_OWN_NAME = "My goal"


def goal_words(goal_name: str) -> str:
    """How the goal reads inside a sentence: "your game", "your Skateboard", "your goal"."""
    if goal_name == DEFAULT_OWN_NAME:
        return "your goal"
    if goal_name in {name for name, _ in PRESETS}:
        return f"your {goal_name.lower()}"
    return f"your {goal_name}"


def summary(plan: GoalPlan, goal_name: str) -> str:
    goal, target = dollars(plan.goal_cents), goal_words(goal_name)
    if plan.already_reached:
        return f"You already have enough for {target}. Little drops filled the jar."
    when = "this week" if plan.weeks == 1 else f"every week for {plan.weeks} weeks"
    text = f"Put {dollars(plan.per_week_cents)} in your jar {when} to reach {goal} for {target}."
    if plan.saved_cents:
        text += f" That counts the {dollars(plan.saved_cents)} you already have."
    if plan.interest_cents:
        text += f" The bank adds {dollars(plan.interest_cents)} in interest along the way."
    return text


def chart_rows(plan: GoalPlan) -> list[dict[str, float | int]]:
    return [{"Week": i + 1, "Balance": cents / 100} for i, cents in enumerate(plan.balances_cents)]


def next_prompt(index: int) -> int:
    return (index + 1) % len(FAMILY_PROMPTS)
