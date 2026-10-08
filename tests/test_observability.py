from penny.contracts import TraceEvent
from penny.observability import InMemoryTraceSink, NullTraceSink


def event(trace_id: str, kind: str = "agent") -> TraceEvent:
    return TraceEvent(trace_id=trace_id, agent="a", kind=kind)


def test_the_in_memory_sink_records_in_order_and_filters_by_trace():
    sink = InMemoryTraceSink()
    for trace_id, kind in (("t1", "route"), ("t2", "route"), ("t1", "verdict")):
        sink.record(event(trace_id, kind))
    assert [e.kind for e in sink.events] == ["route", "route", "verdict"]
    assert [e.kind for e in sink.for_trace("t1")] == ["route", "verdict"]
    assert sink.for_trace("missing") == []


def test_clear_empties_the_sink():
    sink = InMemoryTraceSink()
    sink.record(event("t1"))
    sink.clear()
    assert sink.events == []


def test_the_null_sink_accepts_and_forgets():
    assert NullTraceSink().record(event("t1")) is None
