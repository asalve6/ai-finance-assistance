"""Trace sinks: where TraceEvents go. The Postgres sink arrives with the data lane (A2)."""

from __future__ import annotations

from penny.contracts import TraceEvent


class InMemoryTraceSink:
    """Keeps events in a list. Used by tests, the demo command and the trace viewer."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    def for_trace(self, trace_id: str) -> list[TraceEvent]:
        return [e for e in self.events if e.trace_id == trace_id]

    def clear(self) -> None:
        self.events.clear()


class NullTraceSink:
    def record(self, event: TraceEvent) -> None:
        return None
