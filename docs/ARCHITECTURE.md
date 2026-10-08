# Architecture: the Penny workflow

One LangGraph `StateGraph` handles every question a child asks. Real decisions sit behind three small
interfaces (`src/penny/graph/types.py`), so each can be replaced without touching the graph.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	intake(intake)
	router(router)
	finance_qa(finance_qa)
	coach(coach)
	market(market)
	portfolio(portfolio)
	tax(tax)
	guardian(guardian)
	fallback(fallback)
	respond(respond)
	__end__([<p>__end__</p>]):::last
	__start__ --> intake;
	coach --> guardian;
	fallback --> respond;
	finance_qa --> guardian;
	guardian -.-> coach;
	guardian -.-> fallback;
	guardian -.-> finance_qa;
	guardian -.-> market;
	guardian -.-> portfolio;
	guardian -.-> respond;
	guardian -.-> tax;
	intake --> router;
	market --> guardian;
	portfolio --> guardian;
	router -.-> coach;
	router -.-> finance_qa;
	router -.-> market;
	router -.-> portfolio;
	router -.-> tax;
	tax --> guardian;
	respond --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

Regenerate with `uv run python -m penny.graph.demo --diagram`.

## One turn

1. **intake** adds the question to the session history and resets the turn-scoped fields.
2. **router** picks a specialist (`finance_qa`, `coach`, `market`, `portfolio` or `tax`). An unknown
   answer or a crash falls back to `finance_qa`, so the conversation never breaks.
3. The **specialist** drafts a reply. A crash is treated like a rejected draft.
4. The **guardian** reviews the draft. If it is rejected, the same specialist is called again with the
   Guardian's reasons as feedback, up to `max_retries` times (default 2). If the Guardian itself fails,
   the draft is not let through.
5. After the retries run out, **fallback** gives a short, kind, safe reply.
6. **respond** stores the final reply in the session history and ends the turn.

Every step records a `TraceEvent` (route, agent, verdict, fallback, respond) with its latency.

## Memory

A checkpointer keeps state per `session_id`, so later questions see earlier turns (`AgentRequest.history`).
Different sessions never see each other. The classes stored in the state are registered in
`STATE_TYPES` in `build.py`, which also works with LangGraph's strict serialization mode.

## What is a stand-in today

| Piece | Today (C2) | Replaced by |
|---|---|---|
| Router | `KeywordRouter`: first matching keyword group | E7: LLM classification, mixed questions |
| Specialists | `StubSpecialist`: echoes the question | E1 Finance Q&A, E2 Coach, E3 Market, E4 Portfolio, E5 Tax |
| Guardian | `RuleGuardian`: empty replies, advice and promise wording | E6: LLM review (tone, reading level, facts) on top |
| Trace sink | `InMemoryTraceSink` | A2: Postgres, for the trace viewer |

## Try it

```bash
uv run python -m penny.graph.demo "why is my paycheck smaller?" "what is a stock?"
```
