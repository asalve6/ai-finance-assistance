import json

import pytest

from penny.agents.coach import COACH_UNSURE, CoachAgent, coach_tools, dollars
from penny.agents.guardian import TRUSTED_REPLIES, LLMGuardian
from penny.agents.loop import AgentError
from penny.contracts import Level, LLMResponse, Message, ToolCall
from penny.graph.build import PennyGraph
from penny.graph.stubs import default_agents
from penny.graph.types import AgentRequest, KidContext
from penny.llm.errors import LLMError
from penny.llm.fake import FakeLLM
from penny.observability import InMemoryTraceSink


def says(text: str) -> LLMResponse:
    return LLMResponse(text=text)


def calls(name: str, call_id: str = "c1", **arguments) -> LLMResponse:
    call = ToolCall(id=call_id, name=name, input=arguments)
    return LLMResponse(tool_calls=[call], stop_reason="tool_use")


def request(question: str, level=Level.STARTER, **kwargs) -> AgentRequest:
    return AgentRequest(
        trace_id="t1", kid=KidContext(nickname="Sam", level=level), question=question, **kwargs
    )


def tool(name: str, level=Level.STARTER):
    return next(t for t in coach_tools(level) if t.name == name)


# ------------------------------------------------------------------ the tools


def test_dollars_formats_cents_for_the_model_to_repeat():
    assert [dollars(c) for c in (750, 6000, 5, 0, -450)] == [
        "$7.50",
        "$60.00",
        "$0.05",
        "$0.00",
        "-$4.50",
    ]


def test_plan_goal_tool_gives_ready_to_say_amounts():
    out = tool("plan_goal").fn(goal_cents=6000, weeks=8)
    assert out == {
        "save_each_week": "$7.50",
        "weeks": 8,
        "goal": "$60.00",
        "already_saved": "$0.00",
        "total_you_put_in": "$60.00",
        "interest_earned": "$0.00",
        "balance_at_the_end": "$60.00",
        "goal_already_reached": False,
    }


def test_plan_goal_tool_uses_savings_and_interest():
    out = tool("plan_goal").fn(goal_cents=6000, weeks=8, saved_cents=2000)
    assert (out["save_each_week"], out["already_saved"]) == ("$5.00", "$20.00")
    with_interest = tool("plan_goal").fn(goal_cents=100_000, weeks=104, yearly_interest_pct=5)
    assert with_interest["interest_earned"] != "$0.00"


def test_weeks_to_goal_tool():
    out = tool("weeks_to_goal").fn(goal_cents=6000, per_week_cents=700)
    assert out == {
        "weeks_needed": 9,
        "saving_each_week": "$7.00",
        "goal": "$60.00",
        "already_saved": "$0.00",
    }


def test_try_lemonade_day_tool_matches_the_game():
    out = tool("try_lemonade_day").fn(weather="sunny", price_cents=75, cups=20)
    assert out == {
        "weather": "Sunny and hot",
        "price_per_cup": "$0.75",
        "cups_made": 20,
        "customers_who_wanted_a_cup": 20,
        "cups_sold": 20,
        "cups_unsold": 0,
        "customers_missed": 0,
        "money_in": "$15.00",
        "cost_of_supplies": "$4.00",
        "profit": "$11.00",
    }


def test_the_lemonade_tool_uses_the_readers_level_and_can_show_a_loss():
    starter = tool("try_lemonade_day", Level.STARTER).fn(weather="rainy", price_cents=100, cups=30)
    builder = tool("try_lemonade_day", Level.BUILDER).fn(weather="rainy", price_cents=100, cups=30)
    assert starter["profit"].startswith("-$") and starter["cost_of_supplies"] == "$6.00"
    assert builder["cost_of_supplies"] == "$9.00"


def test_game_rules_tool_reports_money_as_dollars_under_plain_names():
    piggy = tool("game_rules").fn(game="piggy")
    assert (piggy["goal"], piggy["allowance_per_week"], piggy["weeks"]) == ("$30.00", "$10.00", 4)
    lemon = tool("game_rules", Level.SAVER).fn(game="lemonade")
    assert lemon["cost_per_cup"] == "$0.25" and lemon["price_range"] == ["$0.25", "$1.50"]
    assert not [key for key in {**piggy, **lemon} if "cents" in key]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("plan_goal", {"goal_cents": 0, "weeks": 8}),
        ("plan_goal", {"goal_cents": 6000, "weeks": 0}),
        ("plan_goal", {"goal_cents": 6000}),
        ("weeks_to_goal", {"goal_cents": 6000, "per_week_cents": 0}),
        ("try_lemonade_day", {"weather": "snowy", "price_cents": 75, "cups": 20}),
        ("try_lemonade_day", {"weather": "sunny", "price_cents": 5, "cups": 20}),
        ("game_rules", {"game": "chess"}),
    ],
)
def test_tools_refuse_bad_arguments(name, arguments):
    with pytest.raises(ValueError):  # pydantic's ValidationError is a ValueError too
        tool(name).fn(**arguments)


def test_the_coach_has_exactly_four_tools_with_real_descriptions():
    tools = coach_tools(Level.STARTER)
    assert [t.name for t in tools] == [
        "plan_goal",
        "weeks_to_goal",
        "try_lemonade_day",
        "game_rules",
    ]
    assert all(len(t.description) > 60 for t in tools)


# ------------------------------------------------------------------ answering


def test_a_goal_question_is_answered_from_the_tools_result():
    llm = FakeLLM(
        [
            calls("plan_goal", goal_cents=6000, weeks=8),
            says("Save $7.50 each week for 8 weeks. Little drops fill the jar."),
        ]
    )
    reply = CoachAgent(llm, "main-m").respond(request("I want a $60 game in 8 weeks"))
    assert reply.text == "Save $7.50 each week for 8 weeks. Little drops fill the jar."
    assert reply.citations == []
    assert reply.evidence.startswith('plan_goal({"goal_cents": 6000, "weeks": 8}) -> ')
    assert '"save_each_week": "$7.50"' in reply.evidence
    # the model was sent the tool's result before it wrote the answer
    result = llm.calls[1]["messages"][-1]
    assert result.role == "tool" and json.loads(result.content)["save_each_week"] == "$7.50"


def test_a_number_with_no_tool_behind_it_is_replaced():
    llm = FakeLLM([says("You should save about $5 a week.")])
    reply = CoachAgent(llm, "m").respond(request("how much should I save"))
    assert reply.text == COACH_UNSURE and reply.evidence == ""


def test_with_no_tool_behind_it_any_reply_becomes_the_fixed_question():
    for draft in ("What are you saving for, and how much does it cost?", "Saving is great!"):
        reply = CoachAgent(FakeLLM([says(draft)]), "m").respond(request("how do I save for a bike"))
        assert reply.text == COACH_UNSURE and reply.evidence == ""


def test_a_tool_that_only_failed_does_not_count_as_backing_for_a_number():
    llm = FakeLLM([calls("plan_goal", goal_cents=6000, weeks=0), says("Save $7.50 a week.")])
    reply = CoachAgent(llm, "m").respond(request("a $60 game"))
    assert reply.text == COACH_UNSURE
    assert llm.calls[1]["messages"][-1].is_error is True


def test_several_tool_results_are_all_passed_on_as_evidence():
    llm = FakeLLM(
        [
            calls("try_lemonade_day", "c1", weather="rainy", price_cents=100, cups=30),
            calls("try_lemonade_day", "c2", weather="rainy", price_cents=50, cups=8),
            says("At $1.00 you would lose money. At $0.50 with 8 cups you would make a profit."),
        ]
    )
    reply = CoachAgent(llm, "m").respond(request("what if it rains"))
    lines = reply.evidence.splitlines()
    assert len(lines) == 2 and all(line.startswith("try_lemonade_day(") for line in lines)


def test_the_fixed_reply_is_trusted_by_the_guardian_and_has_no_numbers():
    assert COACH_UNSURE in TRUSTED_REPLIES
    assert not any(ch.isdigit() for ch in COACH_UNSURE)


# ------------------------------------------------------------------ prompt and context


def test_the_prompt_has_the_coachs_rules_pennys_values_and_the_reading_level():
    llm = FakeLLM([says("ok")])
    CoachAgent(llm, "main-m").respond(request("hi", Level.SAVER))
    call = llm.calls[0]
    assert call["model"] == "main-m"
    for phrase in (
        "a child called Sam",
        "saving goals and with the Piggy Bank and Lemonade Stand games",
        "Never do money maths yourself",
        "$60 is 6000",
        "Penny's values",
        "3 to 5 short sentences",
    ):
        assert phrase in call["system"], phrase
    assert [t.name for t in call["tools"]] == [
        "plan_goal",
        "weeks_to_goal",
        "try_lemonade_day",
        "game_rules",
    ]


def test_guardian_feedback_and_recent_history_are_included():
    history = [Message.user("I want a bike"), Message(role="assistant", content="How much is it?")]
    llm = FakeLLM([says("ok")])
    CoachAgent(llm, "m").respond(request("it costs $120", history=history, feedback=["shorter"]))
    call = llm.calls[0]
    assert "safety reviewer" in call["system"] and "- shorter" in call["system"]
    assert [(m.role, m.content) for m in call["messages"]] == [
        ("user", "I want a bike"),
        ("assistant", "How much is it?"),
        ("user", "it costs $120"),
    ]


def test_model_calls_and_tool_calls_are_traced_under_the_coachs_name():
    sink = InMemoryTraceSink()
    llm = FakeLLM([calls("game_rules", game="piggy"), says("You get a weekly allowance.")])
    CoachAgent(llm, "m", sink=sink).respond(request("how does the piggy game work"))
    assert [(e.agent, e.kind, e.name) for e in sink.for_trace("t1")] == [
        ("coach", "llm", "m"),
        ("coach", "tool", "game_rules"),
        ("coach", "llm", "m"),
    ]


def test_failures_pass_through_for_the_graph_to_handle():
    class Down:
        def complete(self, **kwargs):
            raise LLMError("down", retryable=True)

    with pytest.raises(LLMError):
        CoachAgent(Down(), "m").respond(request("hi"))
    stuck = FakeLLM([calls("game_rules", game="piggy")] * 5)
    with pytest.raises(AgentError, match="no final answer"):
        CoachAgent(stuck, "m").respond(request("hi"))


# ------------------------------------------------------------------ inside the graph


def test_in_the_graph_a_goal_question_is_routed_to_the_coach_and_reviewed_with_its_evidence():
    approve = LLMResponse(text='{"approved": true, "problems": []}')
    llm = FakeLLM(
        [calls("plan_goal", goal_cents=6000, weeks=8), says("Save $7.50 each week."), approve]
    )
    graph = PennyGraph(
        agents={**default_agents(), "coach": CoachAgent(llm, "main-m")},
        guardian=LLMGuardian(llm, "fast-m"),
    )
    result = graph.ask("how much do I save per week for a $60 game in 8 weeks", session_id="s")
    assert (result.route, result.reply, result.approved) == ("coach", "Save $7.50 each week.", True)
    case = llm.calls[2]["messages"][0].content
    assert "Evidence:\nplan_goal(" in case and "$7.50" in case
