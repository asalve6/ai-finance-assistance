"""The specialist agents, built from the shared pieces. `runtime.build_penny` wires them in."""

from __future__ import annotations

from penny.agents.knowledge import KnowledgeAgent
from penny.contracts import TraceSink
from penny.kb.index import KBIndex
from penny.llm.factory import LLMSetup

TAX_ROLE = (
    "You explain what taxes are and how they work, for learning only. Tax rules differ from place "
    "to place and change over time, so never state a tax rate, amount or deadline unless it is in "
    "the passages. Never tell the child or their family what to do about their own taxes. If the "
    "question is about someone's own tax situation, say that a grown-up or a tax professional can "
    "help with that."
)
TAX_NOTE = "This is for learning, not tax advice."


def build_finance_qa(
    setup: LLMSetup, index: KBIndex, sink: TraceSink | None = None
) -> KnowledgeAgent:
    return KnowledgeAgent(setup.client, setup.main_model, index, name="finance_qa", sink=sink)


def build_tax(setup: LLMSetup, index: KBIndex, sink: TraceSink | None = None) -> KnowledgeAgent:
    """Same grounded Q&A machinery, with a tax-specific role and a disclaimer added in code."""
    return KnowledgeAgent(
        setup.client,
        setup.main_model,
        index,
        name="tax",
        role=TAX_ROLE,
        closing_note=TAX_NOTE,
        sink=sink,
    )
