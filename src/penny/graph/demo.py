"""Try the workflow without any LLM or key (stub agents):

    python -m penny.graph.demo "why is my paycheck smaller?" "what is a stock?"
    python -m penny.graph.demo --diagram

Several questions run in one session, so you can see the conversation history carry over.
"""

from __future__ import annotations

import argparse

from penny.contracts import Level
from penny.graph.build import PennyGraph
from penny.graph.types import KidContext
from penny.observability import InMemoryTraceSink


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m penny.graph.demo")
    parser.add_argument("questions", nargs="*", help="questions to ask, in order, in one session")
    parser.add_argument("--level", choices=[level.value for level in Level], default="starter")
    parser.add_argument("--diagram", action="store_true", help="print the graph as Mermaid")
    args = parser.parse_args(argv)

    sink = InMemoryTraceSink()
    graph = PennyGraph(sink=sink)
    if args.diagram:
        print(graph.mermaid())
        return 0
    if not args.questions:
        parser.error("give at least one question, or use --diagram")

    kid = KidContext(level=Level(args.level))
    for question in args.questions:
        result = graph.ask(question, session_id="demo", kid=kid)
        print(f"\nYou:   {question}")
        print(f"Route: {result.route} ({result.route_reason})")
        print(f"Penny: {result.reply}")
        for event in sink.for_trace(result.trace_id):
            line = f"{event.agent:<10} {event.kind:<8} {event.latency_ms:>3} ms  {event.output}"
            print(f"   trace  {line}")
    print(f"\nSession history: {len(graph.history('demo'))} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
