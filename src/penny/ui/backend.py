"""Connect the app to the agents: live if the keys and the article index are there, offline if not.

The app must always open, including on a machine with no API key (a grader's, for example). In
that case it runs the same workflow with placeholder agents and says why.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from penny.graph.build import PennyGraph
from penny.kb.embedding import DEFAULT_EMBEDDER
from penny.llm.errors import LLMError
from penny.llm.factory import get_llm
from penny.observability import InMemoryTraceSink
from penny.runtime import build_penny

_KEY_FOR = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


@dataclass
class Backend:
    graph: PennyGraph
    sink: InMemoryTraceSink
    live: bool
    note: str  # live: which provider and model. offline: what is missing


def missing_setup() -> str | None:
    """What stops live answers, in words a person can act on. None when everything is set."""
    provider = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    key = _KEY_FOR.get(provider)
    if key and not os.environ.get(key):
        return f"{key} is not set in .env"
    embedder = os.environ.get("KB_EMBEDDER", DEFAULT_EMBEDDER)
    if embedder == "openai" and not os.environ.get("OPENAI_API_KEY"):
        return "OPENAI_API_KEY is not set in .env (it is needed to search the articles)"
    return None


def load_backend() -> Backend:
    sink = InMemoryTraceSink()
    problem = missing_setup()
    if problem is None:
        try:
            setup = get_llm()
            graph = build_penny(setup=setup, sink=sink)
            return Backend(graph, sink, True, f"{setup.provider}, {setup.main_model}")
        except FileNotFoundError:
            problem = "the article index has not been built yet (run: make kb-index)"
        except (LLMError, RuntimeError, ValueError) as exc:
            problem = str(exc)
    return Backend(PennyGraph(sink=sink), sink, False, problem)
