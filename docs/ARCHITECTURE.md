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
| Router | Real: `LLMRouter` (E7) on the fast model, with recent turns for follow-ups. Falls back to `KeywordRouter` if the model fails. A mixed question's other part comes back as `also_ask`, shown as a button | - |
| Specialists | All real: `finance_qa` (E1), `tax` (E5), `coach` (E2), `market` (E3) and `portfolio` (E4) | - |
| Guardian | Real: `LLMGuardian` (E6), rules first, then a model review on the main model | - |
| Trace sink | `InMemoryTraceSink` | A2: Postgres, for the trace viewer |

## The agent loop

Real agents run on `run_agent` (`src/penny/agents/loop.py`): call the model, run the tools it asks for,
send the results back, repeat, capped at `max_steps`. An agent can only use the tools it was given.
Failing tools, unknown tools and invalid arguments go back to the model as error results. A cut-off
answer or a refusal raises `AgentError`, which the graph treats as a rejected draft.

## Finance Q&A (grounded answers)

`KnowledgeAgent` (`src/penny/agents/knowledge.py`) answers only from reviewed articles:

1. The code searches the index first. The reader's level is a preference: an article at or below it
   is used if it scores at least 85% of the best match. A harder article is used when nothing at their
   level matches, or when it answers much better ("What is a stock?" for a starter reader), with a
   note to the writer to explain it extra simply.
2. The model writes a short answer from those passages. It may search again (`search_articles`, at
   most twice), which rescues follow-ups such as "tell me more".
3. **"I don't know" is enforced in code.** If no search in the turn found a confident match, the model's
   text is discarded and a fixed reply is returned. Greetings and thanks are the only exception.

The **Tax** agent is the same machinery with a tax-specific role (no rates or amounts unless the
article has them, personal tax questions go to a grown-up or a tax professional) and a disclaimer
that is appended in code, so it never depends on the model remembering it.

Sources come back as citations and are shown under the answer. Only articles that matched nearly as
well as the best one are cited. `src/penny/runtime.py` wires the real
agents into the graph. Agents not built yet stay as stubs there.

## The Coach (answers from tools)

`CoachAgent` (`src/penny/agents/coach.py`) handles saving goals and the two games. It never does money
maths itself. Every number comes from a tool that runs our own deterministic code:

| Tool | What it runs |
|---|---|
| `plan_goal` | `engines/goal.py`: weekly amount to reach a goal, with savings and optional interest |
| `weeks_to_goal` | `engines/goal.py`: how long a weekly amount takes |
| `try_lemonade_day` | `engines/lemonade.py`: a "what if" day, the same maths as the game |
| `game_rules` | the rules of a game, from the engine's own numbers |

Tools return amounts already written as dollars ("$7.50"), so the model repeats them instead of
converting cents. **Enforced in code:** a reply that contains a number when no tool ran successfully is
replaced by a fixed question asking for the details. The tool results travel with the reply as
evidence, so the Guardian checks the numbers against them.

## The Market agent (live prices, explained)

`MarketAgent` (`src/penny/agents/market_agent.py`) answers "what's Roblox's price?" with three tools:
`find_ticker` (company name to ticker, for Penny's watchlist of ten companies children know),
`get_quote` and `get_price_history`. Prices come from the market chain (`src/penny/market/`):
Yahoo Finance, then Alpha Vantage, then sample data, behind a 30-minute cache. Tools report a change
as a direction and a size ("down", "3.09%"), so replies never say "down by -3.09%".

Enforced in code, as for the Coach (`agents/grounding.py`): a number with no successful tool behind it
replaces the reply with a fixed question. If any price came from sample data, the reply must say so,
and a note is added when it does not. The agent explains; it never predicts or says whether to buy.

## The Guardian

Every reply passes `LLMGuardian` (`src/penny/agents/guardian.py`) before a child sees it. Three layers,
cheapest first:

1. **Rules in code** (`RuleGuardian`): empty replies, advice or promise wording, too many sentences for
   the reader's level, lists, headings or bold. Free, instant, always the same answer.
2. **Fixed replies we wrote**, such as "I don't know that one yet", are trusted without a model call.
3. **A model review** on the main model for what rules cannot see: one-sided claims, facts the evidence
   does not support, unkind tone, words too hard for the reader, privacy.

The reviewer sees only the reading level, the question, the evidence (the passages the writer used)
and the draft. It does not see the writer's prompt or the conversation. Its problems go back to the
writer as feedback for the rewrite. It **fails closed**: if the reviewer is down or returns no verdict,
the reply is not shown and the safe fallback is used after the retries.

## The app (Streamlit)

`make run` starts **Penny the pig** (`src/penny/ui/`). It uses Streamlit's default light theme with one
brand color (`.streamlit/config.toml`) and no custom CSS.

| Part | File | What it does |
|---|---|---|
| Setup | `setup.py`, `quiz.py` | Nickname and a three-question quiz, scored in code, that sets the level |
| Sidebar | `sidebar.py` | Level, coins, drop streak, XP and goal |
| Chat tab | `chat.py`, `chat_model.py` | Asks the graph. Shows the answer, its sources, and the trace in plain words |
| Play tab | `play.py`, `games.py` | Piggy Bank and Lemonade Stand, running the real engines |
| Goals tab | `goal_tab.py`, `goals.py` | Pick a goal, see the weekly amount from the goal planner (with optional savings and interest), a week-by-week chart, and the family challenge |
| Backend | `backend.py` | Live agents when the keys and the article index exist, otherwise an offline demo |

Pages are thin. The logic they call (`quiz`, `session`, `games`, `chat_model`, `backend`) is plain Python
and is tested without Streamlit. The pages themselves are tested headlessly with Streamlit's `AppTest`.

**The app always opens.** With no API key or no built index it runs in offline demo mode: the chat uses
placeholder agents and says what is missing, and the games work fully, because they need no model.

The player's progress lives in the browser session and is lost when the tab closes. Saving it needs the
database (lane A).

## Evaluation

`make evals` runs four suites against the real models, prices and article index, and writes
[docs/evals/report.md](evals/report.md) (plus `report.json` for comparing runs). The cases are
plain YAML in `data/evals/`, so adding one needs no code.

| Suite | What it measures |
|---|---|
| routing | the right specialist for each question, follow-ups using the earlier turns, and mixed questions split into `also_ask` (with no false splits) |
| guardian | planted bad drafts (advice, promises, one-sided, unsupported, unkind, too hard, privacy) are rejected, and good ones approved |
| retrieval | the right article comes back first, and off-topic questions match nothing. Articles not reviewed yet are skipped, not failed |
| answers | whole questions through the graph: route, Guardian approval, text checks on the reply, rewrites, tokens and latency |

`make cov` runs every test with line and branch coverage and fails below 90% (99% today).
`make test` checks the eval code itself with fakes, so it never calls a model. Use
`make evals ARGS="--repeat 3"` to see how much the model-based numbers vary between runs.

Known issue the evals have shown: at the starter reading level the Guardian's model review is
sometimes stricter than needed (a fair draft called "too hard", or asking a goal's price called
private), so an occasional answer ends in the safe fallback. It fails safe, never unsafe. See the
latest report for how often.

## Try it

```bash
uv run python -m penny.graph.demo "why is my paycheck smaller?" "what is a stock?"   # stubs, no key
uv run python -m penny.graph.demo --live "what is a stock?" "tell me more"         # real LLM + index
```

`--live` needs a key in `.env` and a built index (`make kb-index`).
