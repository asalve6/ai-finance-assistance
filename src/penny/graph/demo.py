"""Try the workflow from the command line.

    python -m penny.graph.demo "why is my paycheck smaller?" "what is a stock?"   # stubs, no key
    python -m penny.graph.demo --live "what is a stock?"                          # real LLM + index
    python -m penny.graph.demo --diagram

Several questions run in one session, so you can see the conversation history carry over.
`--live` needs a key in .env and a built index (`make kb-index`).
"""

from __future__ import annotations

import argparse

from penny.config import load_env
from penny.contracts import Level
from penny.graph.build import PennyGraph
from penny.graph.types import KidContext
from penny.llm.errors import LLMError
from penny.observability import InMemoryTraceSink


def _live_graph(sink: InMemoryTraceSink) -> PennyGraph:
    from penny.runtime import build_penny  # imported late: it pulls in the LLM and index code

    return build_penny(sink=sink)


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m penny.graph.demo")
    parser.add_argument("questions", nargs="*", help="questions to ask, in order, in one session")
    parser.add_argument("--level", choices=[level.value for level in Level], default="starter")
    parser.add_argument("--live", action="store_true", help="use the real LLM and article index")
    parser.add_argument("--diagram", action="store_true", help="print the graph as Mermaid")
    args = parser.parse_args(argv)

    sink = InMemoryTraceSink()
    if args.diagram:
        print(PennyGraph().mermaid())
        return 0
    if not args.questions:
        parser.error("give at least one question, or use --diagram")

    try:
        graph = _live_graph(sink) if args.live else PennyGraph(sink=sink)
    except FileNotFoundError:
        print("Error: no article index found. Build one first: make kb-index")
        return 2
    except (LLMError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 2

    kid = KidContext(level=Level(args.level))
    for question in args.questions:
        result = graph.ask(question, session_id="demo", kid=kid)
        print(f"\nYou:   {question}")
        print(f"Route: {result.route} ({result.route_reason})")
        print(f"Penny: {result.reply}")
        for citation in result.citations:
            print(f"   source  {citation.title}")
        if result.fallback_used:
            print(f"   (safe fallback used: {'; '.join(result.last_issues)})")
        for event in sink.for_trace(result.trace_id):
            line = f"{event.agent:<10} {event.kind:<9} {event.latency_ms:>4} ms  {event.output}"
            print(f"   trace  {line}")
    print(f"\nSession history: {len(graph.history('demo'))} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
