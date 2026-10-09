"""Wire the real pieces together: the configured LLM, the article index and the agents built so far.

Agents that are not built yet stay as stubs, so the app always runs. Replace them here one by one.
"""

from __future__ import annotations

import os

from penny.agents.guardian import LLMGuardian
from penny.agents.specialists import build_coach, build_finance_qa, build_tax
from penny.contracts import TraceSink
from penny.graph.build import PennyGraph
from penny.graph.stubs import default_agents
from penny.kb.embedding import DEFAULT_EMBEDDER, get_embedder
from penny.kb.index import INDEX_DIR, KBIndex
from penny.llm.factory import LLMSetup, get_llm

REAL_AGENTS = ("finance_qa", "tax", "coach")


def load_index() -> KBIndex:
    """The saved article index. Raises FileNotFoundError if `make kb-index` has not been run."""
    return KBIndex.load(get_embedder(os.getenv("KB_EMBEDDER", DEFAULT_EMBEDDER)), INDEX_DIR)


def build_penny(
    *,
    setup: LLMSetup | None = None,
    index: KBIndex | None = None,
    sink: TraceSink | None = None,
) -> PennyGraph:
    setup = setup or get_llm()
    index = index or load_index()
    agents = default_agents()
    agents["finance_qa"] = build_finance_qa(setup, index, sink)
    agents["tax"] = build_tax(setup, index, sink)
    agents["coach"] = build_coach(setup, sink)
    guardian = LLMGuardian(setup.client, setup.fast_model, sink=sink)
    return PennyGraph(agents=agents, guardian=guardian, sink=sink)
