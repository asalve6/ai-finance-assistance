"""The Goal and Game Coach: saving goals, and the Piggy Bank and Lemonade Stand games.

The Coach never does money maths itself. Every number it gives comes from a tool that runs our
own deterministic code:

- `plan_goal`         how much to save each week to reach a goal
- `weeks_to_goal`     how many weeks a weekly amount will take
- `try_lemonade_day`  what one lemonade day would look like for a price, cups and weather
- `game_rules`        the rules of a game, straight from the engine

This is enforced in code, not left to the model: if no tool ran successfully in the turn, the
reply is replaced by a fixed question asking for the details (with no tool, the Coach has nothing
checked to say, and in live tests the reviewer kept rejecting its own wording of that question).
The tool results are passed on as evidence, so the Guardian can check the reply against them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from penny.agents.grounding import successful_runs, tool_backed_reply
from penny.agents.loop import run_agent
from penny.agents.prompts import recent_history, system_prompt
from penny.agents.tools import make_tool
from penny.contracts import Level, LLMClient, Message, ToolSpec, TraceSink
from penny.engines import goal, lemonade, piggy
from penny.graph.types import AgentReply, AgentRequest, KidContext
from penny.money import dollars
from penny.observability import NullTraceSink

COACH_ROLE = "You help with saving goals and with the Piggy Bank and Lemonade Stand games."

COACH_UNSURE = (
    "I want to get the numbers right, so I need a bit more. What are you saving for and how much "
    "does it cost, or which game do you want to know about?"
)

_RULES = """\
How to answer:
- Never do money maths yourself. Use a tool for every number you give: my_goal_status, plan_goal,
  weeks_to_goal, try_lemonade_day or game_rules. Tool inputs are in cents: $60 is 6000 and 75
  cents is 75.
- If the child asks how much more they need for the goal they already set, or how it is going,
  call my_goal_status. If they give a price and a number of weeks, use plan_goal instead.
- Say amounts exactly the way the tool wrote them, for example "$7.50".
- If you are missing a detail a tool needs (the price of the goal, how many weeks, the weather),
  ask for it in one short question instead of guessing.
- For a question about how a game works, call game_rules and explain only what it says.
- Say in a sentence what the numbers mean, and connect it to small steady saving when that fits.
- Write plain sentences and stay inside the sentence limit below. No lists, headings or bold.
- This is for learning. Never tell the child what to buy, and never promise that money will grow.
- If the question is not about saving goals or the games, say in one friendly sentence that
  those are what you help with."""


class NoArgs(BaseModel):
    pass


class PlanGoalArgs(BaseModel):
    goal_cents: int = Field(gt=0, description="Price of the goal in cents. $60 is 6000.")
    weeks: int = Field(ge=1, le=520, description="How many weeks there are to save.")
    saved_cents: int = Field(default=0, ge=0, description="Money already saved, in cents.")
    yearly_interest_pct: float = Field(
        default=0, ge=0, le=20, description="Interest rate of a savings account. 0 for a jar."
    )


class WeeksToGoalArgs(BaseModel):
    goal_cents: int = Field(gt=0, description="Price of the goal in cents. $60 is 6000.")
    per_week_cents: int = Field(gt=0, description="Amount saved each week, in cents.")
    saved_cents: int = Field(default=0, ge=0, description="Money already saved, in cents.")


class LemonadeDayArgs(BaseModel):
    weather: Literal["sunny", "cloudy", "rainy"]
    price_cents: int = Field(description="Price of one cup in cents. 75 cents is 75.")
    cups: int = Field(description="How many cups to make.")


class GameRulesArgs(BaseModel):
    game: Literal["piggy", "lemonade"]


def goal_status(goal_name: str, goal_cents: int, saved_cents: int) -> dict[str, Any]:
    """Where the child's saving goal stands right now, in ready-to-say words."""
    left = max(0, goal_cents - saved_cents)
    return {
        "goal": goal_name,
        "price": dollars(goal_cents),
        "already_saved": dollars(saved_cents),
        "still_to_save": dollars(left),
        "percent_saved": f"{min(100, saved_cents * 100 // goal_cents)}%",
        "goal_reached": left == 0,
    }


def coach_tools(level: Level, kid: KidContext | None = None) -> list[ToolSpec]:
    """The Coach's tools for a reader at `level` (the level sets the games' difficulty). `kid`
    supplies the child's own saving goal, for the my_goal_status tool."""
    kid = kid or KidContext(level=level)

    def my_goal_status() -> dict[str, Any]:
        return goal_status(kid.goal_name, kid.goal_cents, kid.saved_cents)

    def plan_goal(
        goal_cents: int, weeks: int, saved_cents: int, yearly_interest_pct: float
    ) -> dict[str, Any]:
        plan = goal.plan_goal(goal_cents, weeks, saved_cents, yearly_interest_pct)
        return {
            "save_each_week": dollars(plan.per_week_cents),
            "weeks": plan.weeks,
            "goal": dollars(plan.goal_cents),
            "already_saved": dollars(plan.saved_cents),
            "total_you_put_in": dollars(plan.deposited_cents),
            "interest_earned": dollars(plan.interest_cents),
            "balance_at_the_end": dollars(plan.balances_cents[-1]),
            "goal_already_reached": plan.already_reached,
        }

    def weeks_to_goal(goal_cents: int, per_week_cents: int, saved_cents: int) -> dict[str, Any]:
        return {
            "weeks_needed": goal.weeks_needed(goal_cents, per_week_cents, saved_cents),
            "saving_each_week": dollars(per_week_cents),
            "goal": dollars(goal_cents),
            "already_saved": dollars(saved_cents),
        }

    def try_lemonade_day(weather: str, price_cents: int, cups: int) -> dict[str, Any]:
        day = lemonade.simulate_day(level, weather, price_cents, cups)
        return {
            "weather": day["weather_label"],
            "price_per_cup": dollars(price_cents),
            "cups_made": day["cups_made"],
            "customers_who_wanted_a_cup": day["demand"],
            "cups_sold": day["cups_sold"],
            "cups_unsold": day["cups_unsold"],
            "customers_missed": day["customers_missed"],
            "money_in": dollars(day["revenue_cents"]),
            "cost_of_supplies": dollars(day["spend_cents"]),
            "profit": dollars(day["profit_cents"]),
        }

    def game_rules(game: str) -> dict[str, Any]:
        rules = piggy.rules(level) if game == "piggy" else lemonade.rules(level)
        friendly: dict[str, Any] = {}
        for key, value in rules.items():
            if "_cents" not in key:
                friendly[key] = value
            elif isinstance(value, list):
                friendly[key.replace("_cents", "")] = [dollars(v) for v in value]
            else:
                friendly[key.replace("_cents", "")] = dollars(value)
        return friendly

    return [
        make_tool(
            "my_goal_status",
            "Look up the goal the child already set on the Goals tab: its name, price, how much is "
            "saved and how much is still to save. Use it only for questions about that existing "
            "goal ('how much more do I need for my bike'). For planning a new amount, use "
            "plan_goal. It takes no arguments.",
            NoArgs,
            my_goal_status,
        ),
        make_tool(
            "plan_goal",
            "Work out how much to save each week to reach a goal by a number of weeks. Use it for "
            "any 'how much should I save' question once you know the price and the weeks.",
            PlanGoalArgs,
            plan_goal,
        ),
        make_tool(
            "weeks_to_goal",
            "Work out how many weeks it takes to reach a goal when saving a fixed amount each "
            "week. Use it for any 'how long will it take' question.",
            WeeksToGoalArgs,
            weeks_to_goal,
        ),
        make_tool(
            "try_lemonade_day",
            "Work out what one Lemonade Stand day would look like for a price, a number of cups "
            "and the weather. Use it for 'what if' and 'why did I lose money' questions. It does "
            "not change any game in progress.",
            LemonadeDayArgs,
            try_lemonade_day,
        ),
        make_tool(
            "game_rules",
            "Get the rules of the Piggy Bank or Lemonade Stand game: goals, costs, how customers "
            "and coins work. Call it before explaining how a game works.",
            GameRulesArgs,
            game_rules,
        ),
    ]


class CoachAgent:
    def __init__(
        self,
        llm: LLMClient,
        model: str,
        *,
        name: str = "coach",
        sink: TraceSink | None = None,
        max_steps: int = 5,
        max_tokens: int | None = 1200,
    ) -> None:
        self.llm = llm
        self.model = model
        self.name = name
        self.sink = sink or NullTraceSink()
        self.max_steps = max_steps
        self.max_tokens = max_tokens

    def respond(self, request: AgentRequest) -> AgentReply:
        result = run_agent(
            self.llm,
            model=self.model,
            system=system_prompt(request, COACH_ROLE, _RULES),
            messages=[*recent_history(request), Message.user(request.question)],
            tools=coach_tools(request.kid.level, request.kid),
            sink=self.sink,
            trace_id=request.trace_id,
            agent=self.name,
            max_steps=self.max_steps,
            max_tokens=self.max_tokens,
        )
        if not successful_runs(result):
            return AgentReply(text=COACH_UNSURE)
        return tool_backed_reply(result, COACH_UNSURE)
