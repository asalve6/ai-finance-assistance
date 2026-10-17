from penny.agents.grounding import SAMPLE_NOTE, disclose_sample_data, used_sample_data
from penny.agents.loop import AgentResult, ToolRun
from penny.graph.types import AgentReply


def run(output: str, is_error: bool = False) -> ToolRun:
    return ToolRun(name="t", input={}, output=output, is_error=is_error)


def test_only_a_top_level_sample_source_counts():
    assert used_sample_data([run('{"source": "sample"}')]) is True
    assert (
        used_sample_data([run('{"source": "yfinance"}'), run('{"inner": {"source": "sample"}}')])
        is False
    )


def test_tool_output_that_is_not_json_is_skipped_not_fatal():
    assert (
        used_sample_data([run("plain text result"), run("[1, 2]"), run('{"source": "sample"}')])
        is True
    )
    assert used_sample_data([run("plain text result")]) is False


def test_failed_tool_runs_do_not_trigger_the_note():
    result = AgentResult(
        text="x", messages=[], steps=1, tool_runs=[run('{"source": "sample"}', is_error=True)]
    )
    reply = disclose_sample_data(AgentReply(text="Disney is a company."), result, set())
    assert reply.text == "Disney is a company."


def test_the_note_is_added_once_and_never_to_fixed_replies():
    result = AgentResult(text="x", messages=[], steps=1, tool_runs=[run('{"source": "sample"}')])
    added = disclose_sample_data(AgentReply(text="It costs $5."), result, set())
    assert added.text == f"It costs $5. {SAMPLE_NOTE}"
    fixed = disclose_sample_data(AgentReply(text="Which company?"), result, {"Which company?"})
    assert fixed.text == "Which company?"
