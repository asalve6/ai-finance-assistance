"""The rule the tool-using agents share: a number in a reply needs a tool behind it.

If a reply contains a digit but no tool ran successfully in the turn, the reply is replaced by
the agent's fixed "tell me more" text. Otherwise the successful tool results travel with the reply
as evidence, so the Guardian can check every number against them.
"""

from __future__ import annotations

import json
import re
from typing import Any

from penny.agents.loop import AgentResult, ToolRun
from penny.graph.types import AgentReply

EVIDENCE_LIMIT = 6000

_DIGIT = re.compile(r"\d")


def successful_runs(result: AgentResult) -> list[ToolRun]:
    return [run for run in result.tool_runs if not run.is_error]


def evidence_from(runs: list[ToolRun]) -> str:
    text = "\n".join(f"{r.name}({json.dumps(r.input)}) -> {r.output}" for r in runs)
    return text[:EVIDENCE_LIMIT]


def tool_backed_reply(result: AgentResult, unsure: str) -> AgentReply:
    text = result.text.strip()
    runs = successful_runs(result)
    if not runs and _DIGIT.search(text):
        return AgentReply(text=unsure)  # a number with no tool behind it is not allowed
    return AgentReply(text=text, evidence=evidence_from(runs))


SAMPLE_NOTE = "These prices are sample data for practice, not live prices."


def used_sample_data(runs: list[ToolRun]) -> bool:
    """True if any tool result says its prices came from sample data (top-level source)."""
    for run in runs:
        try:
            data: Any = json.loads(run.output)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("source") == "sample":
            return True
    return False


def disclose_sample_data(
    reply: AgentReply, result: AgentResult, fixed_replies: set[str]
) -> AgentReply:
    """Make sure a reply built on sample prices says so. Fixed replies are left alone."""
    if (
        reply.text not in fixed_replies
        and used_sample_data(successful_runs(result))
        and "sample" not in reply.text.lower()
    ):
        reply.text = f"{reply.text} {SAMPLE_NOTE}"
    return reply
