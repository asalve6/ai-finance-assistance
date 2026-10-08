import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from penny.contracts import Level, Verdict
from penny.graph import demo
from penny.graph.build import PennyGraph
from penny.graph.stubs import SAFE_FALLBACK, StubSpecialist, default_agents
from penny.graph.types import SPECIALISTS, AgentReply, KidContext, RouteDecision
from penny.kb.retriever import Citation
from penny.observability import InMemoryTraceSink

OK = Verdict(approved=True)


def reject(*reasons: str) -> Verdict:
    return Verdict(approved=False, reasons=list(reasons))


class Scripted:
    """A specialist that replays a script (a reply or an exception per call) and records requests.
    Once the script runs out it repeats the last entry."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def respond(self, request):
        self.requests.append(request)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, AgentReply) else AgentReply(text=item)


class ScriptedGuardian:
    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.calls = []

    def review(self, request, reply):
        self.calls.append((request, reply))
        item = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        if isinstance(item, Exception):
            raise item
        return item


class FixedRouter:
    def __init__(self, decision=None, error=None):
        self.decision, self.error = decision, error

    def route(self, question, history, kid):
        if self.error:
            raise self.error
        return self.decision


def make(specialist=None, guardian=None, sink=None, router=None, **kwargs):
    agents = default_agents()
    if specialist is not None:
        agents["finance_qa"] = specialist
    return PennyGraph(agents=agents, guardian=guardian, sink=sink, router=router, **kwargs)


def kinds(sink, trace_id):
    return [(e.agent, e.kind) for e in sink.for_trace(trace_id)]


# ------------------------------------------------------------------ routing


@pytest.mark.parametrize(
    ("question", "agent"),
    [
        ("why is my paycheck smaller", "tax"),
        ("how do I diversify my portfolio", "portfolio"),
        ("what is the stock price of Nintendo", "market"),
        ("how much do I save per week", "coach"),
        ("what is a stock", "finance_qa"),
    ],
)
def test_each_question_reaches_the_specialist_for_its_topic(question, agent):
    result = PennyGraph().ask(question, session_id="s")
    assert result.route == agent
    assert result.reply.startswith(f"[{agent}]")
    assert agent in SPECIALISTS


def test_an_unknown_route_falls_back_to_the_default_agent():
    router = FixedRouter(RouteDecision(agent="astrologer", reason="because"))
    result = make(router=router).ask("hi", session_id="s")
    assert result.route == "finance_qa"
    assert "unknown agent 'astrologer'" in result.route_reason


def test_a_crashing_router_does_not_break_the_conversation():
    result = make(router=FixedRouter(error=RuntimeError("boom"))).ask("hi", session_id="s")
    assert result.route == "finance_qa"
    assert "router failed: boom" in result.route_reason
    assert result.approved is True


# ------------------------------------------------------------------ the happy path and tracing


def test_a_clean_turn_goes_route_agent_guardian_respond():
    sink = InMemoryTraceSink()
    result = make(sink=sink).ask("what is a stock", session_id="s")
    assert (result.approved, result.rewrites, result.fallback_used) == (True, 0, False)
    assert kinds(sink, result.trace_id) == [
        ("router", "route"),
        ("finance_qa", "agent"),
        ("guardian", "verdict"),
        ("graph", "respond"),
    ]
    events = sink.for_trace(result.trace_id)
    assert events[0].output == {"agent": "finance_qa", "reason": "default"}
    assert events[2].output == {"approved": True, "reasons": []}
    assert all(e.latency_ms >= 0 for e in events)


def test_every_turn_has_its_own_trace_id():
    graph = make()
    first = graph.ask("one", session_id="s")
    second = graph.ask("two", session_id="s")
    assert first.trace_id != second.trace_id


def test_citations_come_through_on_approved_replies():
    citation = Citation(article_id="what-is-a-stock", title="What is a stock?", sources=[])
    specialist = Scripted(AgentReply(text="A stock is a slice.", citations=[citation]))
    result = make(specialist).ask("what is a stock", session_id="s")
    assert result.citations == [citation]


# ------------------------------------------------------------------ the Guardian loop


def test_a_rejected_draft_is_rewritten_with_the_guardians_feedback():
    sink = InMemoryTraceSink()
    specialist = Scripted("draft one", "draft two")
    guardian = ScriptedGuardian(reject("too jargony"), OK)
    result = make(specialist, guardian, sink).ask("what is a stock", session_id="s")

    assert result.reply == "draft two"
    assert (result.approved, result.rewrites, result.fallback_used) == (True, 1, False)
    assert [r.feedback for r in specialist.requests] == [[], ["too jargony"]]
    assert kinds(sink, result.trace_id) == [
        ("router", "route"),
        ("finance_qa", "agent"),
        ("guardian", "verdict"),
        ("finance_qa", "agent"),
        ("guardian", "verdict"),
        ("graph", "respond"),
    ]
    revising = [e.output["revising"] for e in sink.events if e.kind == "agent"]
    assert revising == [False, True]
    # the Guardian saw each draft in turn
    assert [reply.text for _, reply in guardian.calls] == ["draft one", "draft two"]


def test_when_every_draft_is_rejected_the_safe_fallback_is_used_after_two_rewrites():
    sink = InMemoryTraceSink()
    specialist = Scripted("bad")
    result = make(specialist, ScriptedGuardian(reject("no")), sink).ask("q", session_id="s")
    assert len(specialist.requests) == 3  # the first draft plus two rewrites
    assert result.reply == SAFE_FALLBACK
    assert (result.approved, result.fallback_used, result.rewrites) == (False, True, 3)
    assert result.last_issues == ["no"] and result.citations == []
    assert kinds(sink, result.trace_id)[-2:] == [("graph", "fallback"), ("graph", "respond")]


@pytest.mark.parametrize(("max_retries", "attempts"), [(0, 1), (1, 2), (3, 4)])
def test_max_retries_controls_how_many_drafts_are_tried(max_retries, attempts):
    specialist = Scripted("bad")
    graph = make(specialist, ScriptedGuardian(reject("no")), max_retries=max_retries)
    assert graph.ask("q", session_id="s").fallback_used is True
    assert len(specialist.requests) == attempts


def test_a_crashing_specialist_is_retried_and_can_recover():
    sink = InMemoryTraceSink()
    specialist = Scripted(RuntimeError("boom"), RuntimeError("boom"), "recovered")
    guardian = ScriptedGuardian(OK)
    result = make(specialist, guardian, sink).ask("q", session_id="s")
    assert result.reply == "recovered" and result.rewrites == 2
    assert len(guardian.calls) == 1  # crashes never reach the Guardian as drafts
    errors = [e for e in sink.events if e.kind == "error"]
    assert [e.output for e in errors] == [{"error": "boom"}, {"error": "boom"}]
    assert [r.feedback for r in specialist.requests][1] == ["RuntimeError: boom"]


def test_a_specialist_that_always_crashes_ends_in_the_fallback():
    result = make(Scripted(RuntimeError("down"))).ask("q", session_id="s")
    assert result.fallback_used is True and result.reply == SAFE_FALLBACK
    assert result.last_issues == ["RuntimeError: down"]


def test_if_the_safety_check_itself_fails_nothing_is_let_through():
    result = make(Scripted("hello"), ScriptedGuardian(RuntimeError("model down"))).ask(
        "q", session_id="s"
    )
    assert result.fallback_used is True and result.reply == SAFE_FALLBACK
    assert result.last_issues == ["safety review failed: model down"]


def test_the_default_rule_guardian_blocks_advice_and_the_loop_recovers():
    specialist = Scripted("You should buy this stock now.", "A stock is a slice of a company.")
    result = make(specialist).ask("what is a stock", session_id="s")
    assert result.reply == "A stock is a slice of a company."
    assert result.rewrites == 1
    assert "you should buy" in specialist.requests[1].feedback[0]


# ------------------------------------------------------------------ conversation memory


def test_a_session_remembers_earlier_turns_and_other_sessions_do_not():
    specialist = Scripted("first answer", "second answer", "third answer")
    graph = make(specialist)
    graph.ask("question one", session_id="kid-1")
    graph.ask("question two", session_id="kid-1")
    graph.ask("question three", session_id="kid-2")

    assert specialist.requests[0].history == []
    second = specialist.requests[1].history
    assert [(m.role, m.content) for m in second] == [
        ("user", "question one"),
        ("assistant", "first answer"),
    ]
    assert specialist.requests[2].history == []  # a different session starts clean
    assert [m.content for m in graph.history("kid-1")] == [
        "question one",
        "first answer",
        "question two",
        "second answer",
    ]


def test_the_fallback_reply_is_remembered_too():
    graph = make(Scripted("bad"), ScriptedGuardian(reject("no")))
    graph.ask("q", session_id="s")
    assert graph.history("s")[-1].content == SAFE_FALLBACK


def test_turn_state_does_not_leak_into_the_next_turn():
    specialist = Scripted("bad", "bad", "bad", "good")
    guardian = ScriptedGuardian(reject("no"), reject("no"), reject("no"), OK)
    graph = make(specialist, guardian)
    first = graph.ask("one", session_id="s")
    second = graph.ask("two", session_id="s")
    assert first.fallback_used is True
    assert (second.rewrites, second.fallback_used, second.approved) == (0, False, True)
    assert second.last_issues == []
    assert specialist.requests[3].feedback == []


def test_the_specialist_sees_who_is_asking():
    specialist = Scripted("ok")
    kid = KidContext(kid_id=7, nickname="Sam", level=Level.BUILDER)
    make(specialist).ask("q", session_id="s", kid=kid)
    seen = specialist.requests[0].kid
    assert (seen.kid_id, seen.nickname, seen.level) == (7, "Sam", Level.BUILDER)


# ------------------------------------------------------------------ construction and structure


def test_the_default_route_must_exist():
    with pytest.raises(ValueError, match="finance_qa"):
        PennyGraph(agents={"tax": StubSpecialist("tax")})


@pytest.mark.parametrize("name", ["router", "guardian", "fallback", "respond", "intake"])
def test_agent_names_cannot_clash_with_graph_nodes(name):
    agents = {**default_agents(), name: StubSpecialist(name)}
    with pytest.raises(ValueError, match="clash"):
        PennyGraph(agents=agents)


def test_the_diagram_shows_every_node():
    diagram = PennyGraph().mermaid()
    for node in ("intake", "router", "guardian", "fallback", "respond", *SPECIALISTS):
        assert node in diagram


# ------------------------------------------------------------------ session storage


def test_state_round_trips_through_the_checkpoint_without_warnings(caplog):
    graph = PennyGraph()
    with caplog.at_level(logging.WARNING):
        graph.ask("why is my paycheck smaller", session_id="s")
        graph.ask("what is a stock", session_id="s")
        graph.history("s")
    assert "unregistered" not in caplog.text.lower()


def test_it_also_works_in_langgraphs_strict_mode():
    """Strict mode will be the default in a future LangGraph release."""
    code = (
        "from penny.graph.build import PennyGraph\n"
        "g = PennyGraph()\n"
        "g.ask('why is my paycheck smaller', session_id='s')\n"
        "r = g.ask('what is a stock', session_id='s')\n"
        "print(r.route, len(g.history('s')))\n"
    )
    env = {
        **os.environ,
        "LANGGRAPH_STRICT_MSGPACK": "true",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "finance_qa 4"


# ------------------------------------------------------------------ the demo command


def test_the_demo_runs_a_session_and_shows_the_trace(capsys):
    assert demo.main(["why is my paycheck smaller", "what is a stock"]) == 0
    out = capsys.readouterr().out
    assert "Route: tax (matched 'paycheck')" in out
    assert "Route: finance_qa (default)" in out
    assert "trace  router" in out and "trace  guardian" in out
    assert "Session history: 4 messages" in out


def test_the_demo_can_print_the_diagram(capsys):
    assert demo.main(["--diagram"]) == 0
    assert "graph TD" in capsys.readouterr().out


def test_the_demo_needs_a_question_or_the_diagram_flag():
    with pytest.raises(SystemExit) as raised:
        demo.main([])
    assert raised.value.code == 2
