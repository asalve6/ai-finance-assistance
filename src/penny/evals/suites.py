"""The four eval suites. Each takes the piece it measures, so tests can pass fakes.

- routing:   does the router pick the right specialist, and split mixed questions?
- guardian:  does the Guardian reject planted bad drafts and approve good ones?
- retrieval: does the right article come back first, and nothing for off-topic questions?
- answers:   whole questions through the graph: route, approval, and checks on the reply text
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

from penny.contracts import Message
from penny.evals.cases import AnswerCase, GuardianCase, RetrievalCase, RoutingCase
from penny.graph.build import PennyGraph
from penny.graph.types import AgentReply, AgentRequest, Guardian, KidContext, Router
from penny.kb.index import KBIndex
from penny.kb.retriever import retrieve
from penny.observability import InMemoryTraceSink

RETRIEVAL_K = 4


class CaseResult(BaseModel):
    id: str
    passed: bool | None  # None: skipped
    detail: str = ""
    latency_ms: int = 0
    tokens: int = 0


class SuiteResult(BaseModel):
    name: str
    results: list[CaseResult]
    metrics: dict[str, Any] = Field(default_factory=dict)

    @property
    def run(self) -> list[CaseResult]:
        return [r for r in self.results if r.passed is not None]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.run if r.passed)

    @property
    def total(self) -> int:
        return len(self.run)

    @property
    def skipped(self) -> int:
        return len(self.results) - self.total


def rate(count: int, total: int) -> str:
    return f"{count}/{total} ({count / total:.0%})" if total else "n/a"


def _timed(fn: Callable[[], Any]) -> tuple[Any, int]:
    started = time.perf_counter()
    value = fn()
    return value, int((time.perf_counter() - started) * 1000)


def _repeat(cases: Sequence[Any], times: int) -> list[tuple[str, Any]]:
    """Each case `times` times; ids get "#2", "#3"... from the second round."""
    return [
        (case.id if round_ == 1 else f"{case.id}#{round_}", case)
        for round_ in range(1, times + 1)
        for case in cases
    ]


def _latency_metrics(results: list[CaseResult]) -> dict[str, Any]:
    times = sorted(r.latency_ms for r in results if r.passed is not None)
    if not times:
        return {}
    p95 = times[min(len(times) - 1, round(0.95 * (len(times) - 1)))]
    return {"median latency": f"{median(times):.0f} ms", "p95 latency": f"{p95} ms"}


# ------------------------------------------------------------------ routing


def _history(lines: list[str]) -> list[Message]:
    return [
        Message.user(text) if i % 2 == 0 else Message(role="assistant", content=text)
        for i, text in enumerate(lines)
    ]


def run_routing(router: Router, cases: Sequence[RoutingCase], repeat: int = 1) -> SuiteResult:
    results: list[CaseResult] = []
    agent_right = split_right = mixed_total = false_splits = 0
    for case_id, case in _repeat(cases, repeat):
        decision, ms = _timed(
            lambda c=case: router.route(c.question, _history(c.history), KidContext())
        )
        right_agent = decision.agent == case.agent
        agent_right += right_agent
        split = bool(decision.also_ask)
        if case.mixed:
            mixed_total += 1
            split_right += split
        elif split:
            false_splits += 1
        passed = right_agent and split == case.mixed
        detail = f"got {decision.agent}" + (f", also_ask: {decision.also_ask}" if split else "")
        if not right_agent:
            detail += f" (expected {case.agent})"
        elif split != case.mixed:
            detail += " (expected a split)" if case.mixed else " (unexpected split)"
        results.append(CaseResult(id=case_id, passed=passed, detail=detail, latency_ms=ms))
    return SuiteResult(
        name="routing",
        results=results,
        metrics={
            "right specialist": rate(agent_right, len(results)),
            "mixed questions split": rate(split_right, mixed_total),
            "false splits": false_splits,
            **_latency_metrics(results),
        },
    )


# ------------------------------------------------------------------ guardian


def run_guardian(guardian: Guardian, cases: Sequence[GuardianCase], repeat: int = 1) -> SuiteResult:
    results: list[CaseResult] = []
    caught = bad_total = approved_good = good_total = 0
    for case_id, case in _repeat(cases, repeat):
        request = AgentRequest(
            trace_id=case_id, kid=KidContext(level=case.level), question=case.question
        )
        reply = AgentReply(text=case.draft, evidence=case.evidence)
        try:
            verdict, ms = _timed(lambda r=request, d=reply: guardian.review(r, d))
            approved, reasons = verdict.approved, "; ".join(verdict.reasons)
        except Exception as exc:  # the graph treats a failed review as a rejection
            approved, reasons, ms = False, f"review failed: {exc}", 0
        if case.bad:
            bad_total += 1
            caught += not approved
        else:
            good_total += 1
            approved_good += approved
        passed = approved != case.bad
        label = "bad" if case.bad else "good"
        detail = f"{label} draft, {'approved' if approved else 'rejected'}"
        if reasons:
            detail += f": {reasons}"
        results.append(CaseResult(id=case_id, passed=passed, detail=detail, latency_ms=ms))
    return SuiteResult(
        name="guardian",
        results=results,
        metrics={
            "bad drafts caught": rate(caught, bad_total),
            "good drafts approved": rate(approved_good, good_total),
            **_latency_metrics(results),
        },
    )


# ------------------------------------------------------------------ retrieval


def run_retrieval(index: KBIndex, cases: Sequence[RetrievalCase]) -> SuiteResult:
    """Deterministic for a given index, so it runs once."""
    in_index = {chunk.article_id for chunk in index.chunks}
    results: list[CaseResult] = []
    first = in_top = expected_total = quiet = off_topic = 0
    for case in cases:
        acceptable = [a for a in case.acceptable if a in in_index]
        if case.article is not None and not acceptable:
            results.append(
                CaseResult(id=case.id, passed=None, detail=f"{case.article} is not in the index")
            )
            continue
        found, ms = _timed(lambda c=case: retrieve(index, c.question, k=RETRIEVAL_K))
        articles = [c.article_id for c in found.citations()]
        if case.article is None:
            off_topic += 1
            passed = not found.confident
            quiet += passed
            detail = (
                "nothing matched" if passed else f"matched {articles[0]} ({found.top_score:.2f})"
            )
        else:
            expected_total += 1
            passed = bool(articles) and articles[0] in acceptable
            first += passed
            in_top += any(a in articles for a in acceptable)
            detail = (
                f"top: {articles[0]} ({found.top_score:.2f})" if articles else "nothing matched"
            )
        results.append(CaseResult(id=case.id, passed=passed, detail=detail, latency_ms=ms))
    return SuiteResult(
        name="retrieval",
        results=results,
        metrics={
            "articles in the index": len(in_index),
            "right article first": rate(first, expected_total),  # or one listed in also_ok
            f"right article in top {RETRIEVAL_K}": rate(in_top, expected_total),
            "off-topic left unmatched": rate(quiet, off_topic),
        },
    )


# ------------------------------------------------------------------ answers


def check_answer(case: AnswerCase, result: Any) -> list[str]:
    """What is wrong with one end-to-end answer. Empty when it passes."""
    problems = []
    if case.route is not None and result.route != case.route:
        problems.append(f"routed to {result.route}, expected {case.route}")
    if result.approved != case.approved:
        problems.append("used the safe fallback" if case.approved else "was approved")
    text = result.reply.lower()
    problems += [f'missing "{w}"' for w in case.contains if w.lower() not in text]
    problems += [f'should not say "{w}"' for w in case.not_contains if w.lower() in text]
    if case.also_ask is not None and bool(result.also_ask) != case.also_ask:
        problems.append("no second part offered" if case.also_ask else "offered a second part")
    return problems


def run_answers(
    graph: PennyGraph, sink: InMemoryTraceSink, cases: Sequence[AnswerCase], repeat: int = 1
) -> SuiteResult:
    results: list[CaseResult] = []
    routed = approved = fallbacks = rewrites = 0
    for case_id, case in _repeat(cases, repeat):
        kid = KidContext(
            level=case.level,
            practice_holdings=case.holdings,
            goal_name=case.goal_name,
            goal_cents=case.goal_cents,
            saved_cents=case.saved_cents,
        )
        session = f"eval-{case_id}"
        for earlier in case.before:
            graph.ask(earlier, session_id=session, kid=kid)
        try:
            result, ms = _timed(
                lambda c=case, s=session, k=kid: graph.ask(c.question, session_id=s, kid=k)
            )
        except Exception as exc:  # a crash is a failed case, not a failed run
            results.append(CaseResult(id=case_id, passed=False, detail=f"crashed: {exc}"))
            continue
        events = sink.for_trace(result.trace_id)
        tokens = sum(e.input_tokens + e.output_tokens for e in events)
        problems = check_answer(case, result)
        routed += case.route is None or result.route == case.route
        approved += result.approved
        fallbacks += result.fallback_used
        rewrites += result.rewrites
        detail = "; ".join(problems) if problems else f"{result.route}, {result.rewrites} rewrites"
        results.append(
            CaseResult(
                id=case_id,
                passed=not problems,
                detail=f"{detail} | {result.reply[:160]}",
                latency_ms=ms,
                tokens=tokens,
            )
        )
    total = len(results)
    run = [r for r in results if r.passed is not None]
    return SuiteResult(
        name="answers",
        results=results,
        metrics={
            "right specialist": rate(routed, total),
            "approved by the Guardian": rate(approved, total),
            "safe fallback used": rate(fallbacks, total),
            "rewrites per answer": f"{rewrites / total:.2f}" if total else "n/a",
            "tokens per answer": f"{sum(r.tokens for r in run) / len(run):.0f}" if run else "n/a",
            **_latency_metrics(results),
        },
    )
