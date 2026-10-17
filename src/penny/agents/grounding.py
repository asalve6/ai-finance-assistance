"""The rule the tool-using agents share: a number in a reply needs a tool behind it.

If a reply contains a digit but no tool ran successfully in the turn, the reply is replaced by
the agent's fixed "tell me more" text. Otherwise the successful tool results travel with the reply
as evidence, so the Guardian can check every number against them.
"""

from __future__ import annotations

import json
import re

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
