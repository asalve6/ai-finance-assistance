"""The Penny workflow as a LangGraph StateGraph.

    START -> intake -> router -> <specialist> -> guardian -+-> respond -> END
                                      ^                    |
                                      +-- rejected, retries left (with the Guardian's feedback)
                                                           +-> fallback -> respond -> END

State is kept per session by a checkpointer, so a conversation keeps its history across turns.
Turn-scoped fields (route, draft, verdict, rewrites) are reset by `intake` on every question.
"""

from __future__ import annotations

import operator
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from penny.contracts import AgentName, Level, Message, ToolCall, TraceEvent, TraceSink, Verdict
from penny.graph.stubs import SAFE_FALLBACK, KeywordRouter, RuleGuardian, default_agents
from penny.graph.types import (
    RESERVED_NODE_NAMES,
    AgentReply,
    AgentRequest,
    Guardian,
    KidContext,
    RouteDecision,
    Router,
    Specialist,
    TurnResult,
)
from penny.kb.article import Source
from penny.kb.retriever import Citation
from penny.observability import NullTraceSink

DEFAULT_AGENT = "finance_qa"

# Our own classes that appear inside the state. LangGraph refuses to rebuild unregistered classes
# from a checkpoint, so each one is listed here. Add a class here if you add it to `State`.
STATE_TYPES = (Level, Message, ToolCall, Verdict, KidContext, AgentReply, Citation, Source)


def checkpoint_serializer() -> JsonPlusSerializer:
    allowed = [(t.__module__, t.__name__) for t in STATE_TYPES]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


class State(TypedDict, total=False):
    # Whole session
    history: Annotated[list[Message], operator.add]
    # Input of the current turn
    trace_id: str
    kid: KidContext
    question: str
    # Turn-scoped working state
    route: str
    route_reason: str
    also_ask: str
    draft: AgentReply | None
    agent_error: str | None
    verdict: Verdict | None
    feedback: list[str]
    rewrites: int
    # Turn result
    reply: str
    approved: bool
    fallback_used: bool


class PennyGraph:
    def __init__(
        self,
        agents: Mapping[str, Specialist] | None = None,
        router: Router | None = None,
        guardian: Guardian | None = None,
        sink: TraceSink | None = None,
        *,
        max_retries: int = 2,
    ) -> None:
        self.agents: dict[str, Specialist] = (
            dict(agents) if agents is not None else default_agents()
        )
        if DEFAULT_AGENT not in self.agents:
            raise ValueError(f"an agent named '{DEFAULT_AGENT}' is required as the default route")
        clash = RESERVED_NODE_NAMES & self.agents.keys()
        if clash:
            raise ValueError(f"agent names clash with graph nodes: {sorted(clash)}")
        self.router: Router = router or KeywordRouter()
        self.guardian: Guardian = guardian or RuleGuardian()
        self.sink: TraceSink = sink or NullTraceSink()
        self.max_retries = max_retries
        self.app = self._build()

    # ------------------------------------------------------------------ public API

    def ask(self, question: str, *, session_id: str, kid: KidContext | None = None) -> TurnResult:
        """Run one turn. Turns with the same `session_id` share conversation history."""
        trace_id = uuid.uuid4().hex[:12]
        state = self.app.invoke(
            {"trace_id": trace_id, "kid": kid or KidContext(), "question": question},
            self._config(session_id),
        )
        draft = state.get("draft")
        verdict = state.get("verdict")
        used_fallback = state["fallback_used"]
        return TurnResult(
            reply=state["reply"],
            route=state["route"],
            route_reason=state["route_reason"],
            approved=state["approved"],
            rewrites=state["rewrites"],
            fallback_used=used_fallback,
            trace_id=trace_id,
            citations=[] if used_fallback or draft is None else draft.citations,
            last_issues=[] if verdict is None or verdict.approved else verdict.reasons,
            also_ask="" if used_fallback else state.get("also_ask", ""),
        )

    def history(self, session_id: str) -> list[Message]:
        snapshot = self.app.get_state(self._config(session_id))
        return list(snapshot.values.get("history", []))

    def mermaid(self) -> str:
        return self.app.get_graph().draw_mermaid()

    # ------------------------------------------------------------------ building

    @staticmethod
    def _config(session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}}

    def _emit(
        self,
        state: State,
        agent: str,
        kind: str,
        name: str,
        started: float,
        output: dict[str, Any],
    ) -> None:
        self.sink.record(
            TraceEvent(
                trace_id=state["trace_id"],
                agent=agent,
                kind=kind,
                name=name,
                output=output,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )

    def _request(self, state: State) -> AgentRequest:
        return AgentRequest(
            trace_id=state["trace_id"],
            kid=state["kid"],
            question=state["question"],
            history=state["history"][:-1],  # the last entry is the current question
            feedback=state.get("feedback", []),
            also_ask=state.get("also_ask", ""),
        )

    def _build(self) -> Any:
        graph = StateGraph(State)
        graph.add_node("intake", self._intake)
        graph.add_node("router", self._route)
        for name in self.agents:
            graph.add_node(name, self._specialist(name))
        graph.add_node("guardian", self._review)
        graph.add_node("fallback", self._fallback)
        graph.add_node("respond", self._respond)

        graph.add_edge(START, "intake")
        graph.add_edge("intake", "router")
        graph.add_conditional_edges("router", lambda s: s["route"], {n: n for n in self.agents})
        for name in self.agents:
            graph.add_edge(name, "guardian")
        graph.add_conditional_edges(
            "guardian",
            self._after_review,
            {"respond": "respond", "fallback": "fallback", **{n: n for n in self.agents}},
        )
        graph.add_edge("fallback", "respond")
        graph.add_edge("respond", END)
        return graph.compile(checkpointer=InMemorySaver(serde=checkpoint_serializer()))

    # ------------------------------------------------------------------ nodes

    def _intake(self, state: State) -> dict[str, Any]:
        return {
            "history": [Message.user(state["question"])],
            "route": DEFAULT_AGENT,
            "route_reason": "",
            "also_ask": "",
            "draft": None,
            "agent_error": None,
            "verdict": None,
            "feedback": [],
            "rewrites": 0,
            "reply": "",
            "approved": False,
            "fallback_used": False,
        }

    def _route(self, state: State) -> dict[str, Any]:
        started = time.perf_counter()
        history = state["history"][:-1]
        try:
            decision = self.router.route(
                state["question"], history, state["kid"], trace_id=state["trace_id"]
            )
        except Exception as exc:  # a broken router must not break the conversation
            decision = RouteDecision(agent=DEFAULT_AGENT, reason=f"router failed: {exc}")
        if decision.agent not in self.agents:
            decision = RouteDecision(
                agent=DEFAULT_AGENT, reason=f"unknown agent '{decision.agent}', used the default"
            )
        output = {"agent": decision.agent, "reason": decision.reason, "also_ask": decision.also_ask}
        self._emit(state, "router", "route", "route", started, output)
        return {
            "route": decision.agent,
            "route_reason": decision.reason,
            "also_ask": decision.also_ask,
        }

    def _specialist(self, name: str) -> Callable[[State], dict[str, Any]]:
        def run(state: State) -> dict[str, Any]:
            started = time.perf_counter()
            try:
                draft = self.agents[name].respond(self._request(state))
            except Exception as exc:  # treated like a rejected draft, so it gets retried
                self._emit(state, name, "error", "respond", started, {"error": str(exc)})
                return {"draft": None, "agent_error": f"{type(exc).__name__}: {exc}"}
            output = {
                "chars": len(draft.text),
                "citations": len(draft.citations),
                "revising": bool(state.get("feedback")),
            }
            self._emit(state, name, "agent", "respond", started, output)
            return {"draft": draft, "agent_error": None}

        return run

    def _review(self, state: State) -> dict[str, Any]:
        started = time.perf_counter()
        draft = state.get("draft")
        if draft is None:
            verdict = Verdict(approved=False, reasons=[state.get("agent_error") or "no reply"])
        else:
            try:
                verdict = self.guardian.review(self._request(state), draft)
            except Exception as exc:  # if the safety check itself fails, do not let the reply out
                verdict = Verdict(approved=False, reasons=[f"safety review failed: {exc}"])
        output = {"approved": verdict.approved, "reasons": verdict.reasons}
        self._emit(state, AgentName.GUARDIAN.value, "verdict", "review", started, output)
        if verdict.approved:
            return {"verdict": verdict}
        return {
            "verdict": verdict,
            "feedback": verdict.reasons,
            "rewrites": state.get("rewrites", 0) + 1,
        }

    def _after_review(self, state: State) -> str:
        if state["verdict"].approved:
            return "respond"
        if state["rewrites"] <= self.max_retries:
            return state["route"]  # try again with the Guardian's feedback
        return "fallback"

    def _fallback(self, state: State) -> dict[str, Any]:
        started = time.perf_counter()
        output = {"rewrites": state.get("rewrites", 0)}
        self._emit(state, "graph", "fallback", "safe_reply", started, output)
        return {"reply": SAFE_FALLBACK, "fallback_used": True, "approved": False}

    def _respond(self, state: State) -> dict[str, Any]:
        started = time.perf_counter()
        if state.get("fallback_used"):
            reply, approved = state["reply"], False
        else:
            reply, approved = state["draft"].text, True
        self._emit(state, "graph", "respond", "final", started, {"approved": approved})
        return {
            "reply": reply,
            "approved": approved,
            "history": [Message(role="assistant", content=reply)],
        }
