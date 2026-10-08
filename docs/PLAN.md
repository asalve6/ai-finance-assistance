# Delivery plan (v2, 14 days, graded against the capstone rubric)

## Decisions (locked unless noted)

| Topic | Decision | Why |
|---|---|---|
| Deadline | 14 days | Owner's call |
| Orchestration | **LangGraph `StateGraph`** | 10 rubric points, and it feeds the multi-agent score |
| LLM access | **Adapter pattern**: `LLMClient` contract, one adapter per provider, chosen by `LLM_PROVIDER` | Swap providers with an env var. Tests use `FakeLLM` and need no key |
| Providers to build | Anthropic first, then OpenAI (program key). Gemini only if time allows | Demo with whichever key works |
| Vector store | **FAISS** + `all-MiniLM-L6-v2` (local, free) | No infra |
| Market data | Fallback chain: **yfinance, then Alpha Vantage, then saved sample quotes**, all behind a TTL cache | yfinance has no cap but is unofficial. Alpha Vantage is official but limited to 25 requests a day, so it only runs when yfinance fails |
| App database | Postgres (profiles, ledger, traces, market cache) | Needs Docker. Fallback: Homebrew Postgres |
| MCP server | **Dropped** | Owner's call. Costs up to 5 rubric points. Can be revived late |
| Agent count | **5 specialist agents**, built well (rubric: 4-5 = "Good") | Quality over quantity |
| UI | Streamlit, multi-tab, thin pages over testable modules | Rubric names Streamlit |

### The five agents (plus supporting nodes)

| # | Agent | Kid-facing job | Needs |
|---|---|---|---|
| 1 | **Finance Q&A** | "Ask Penny": answers from the knowledge base with sources, says "I don't know" when retrieval is weak | FAISS, articles |
| 2 | **Goal and Game Coach** | Savings goal math (how much per week), plus explains Piggy and Lemonade results | engines (B1, B2), goal planner |
| 3 | **Market Analysis** | Live quote for a company a kid knows, explained simply | market provider, cache |
| 4 | **Portfolio Analysis** | Practice portfolio: allocation, diversification, risk, with charts | portfolio analytics, market data |
| 5 | **Tax Education** | What taxes are and why, education only, never advice | FAISS, tax articles |

Supporting nodes (not counted as agents): **Router** (classifies and dispatches), **Guardian** (reviews every kid-facing reply, retry up to 2), **Onboarding quiz** (scored in code, LLM only phrases it).
Stretch agent if time remains: News Synthesizer (needs Tavily or SerpApi). The router is built so a sixth agent is one new node.

## Rubric traceability

| Rubric item (weight) | Where it is earned | Target |
|---|---|---|
| Multi-agent architecture (10) | 5 agents + Router + Guardian, distinct tools and prompts | Good to Excellent |
| LangGraph workflow (10) | Typed state, router edges, Guardian retry loop, trace id | Excellent |
| RAG (8) | FAISS, chunking, source attribution, low-confidence refusal | Excellent |
| Real-time data (7) | Provider interface, TTL cache, mock fallback, error handling | Excellent |
| MCP server (5) | **Not built.** Owner decision: not required. Gives up at most 5 points | 0 of 5 |
| Web interface (10) | Streamlit tabs: Chat, Games, Portfolio, Markets, Goals, Knowledge, Parent | Excellent |
| Conversational flow (8) | Session memory in graph state, profile-aware tone | Good |
| Data viz (7) | Allocation chart, price history, goal progress, game profit | Good |
| Knowledge base (8) | 60 articles (Good), 100 stretch (Excellent) | Good |
| Portfolio analysis (7) | Allocation, concentration, volatility, risk score | Good |
| Market intelligence (5) | Quote + plain-language interpretation | Good |
| Code organization (5) | Lanes by package, contracts, no cross-lane imports | Excellent |
| Documentation (5) | README, mermaid architecture diagram, setup guide, demo script | Excellent |
| Testing (5) | `--cov-fail-under=90`, thin UI so logic is covered | Excellent |
| Bonus (10) | Games engines, kid-level adaptation, Guardian, evals, roadmap | partial |

## Working agreement
- One PR = one reviewable idea, under about 300 changed lines, tests included. Branches: `pr/<id>-<slug>` from `main`.
- Nothing is pushed until the owner reviews. Merges to `main` happen only when told.
- Lanes touch their own package only. `contracts.py` changes get their own PR.
- No API keys or `.env` in the repo, ever (submission rule). `.env.example` only.
- Every lane runs without the others: engines are pure, agents use `FakeLLM`, market data has a mock provider.

## Lanes and PRs

Legend: `done` is merged to `main`.

| Lane | PR | Scope | Depends on |
|---|---|---|---|
| 0 | PR 0 | Scaffold, contracts, FakeLLM | done |
| B engines | B1 | Piggy Bank engine | done |
| | B2 | Lemonade engine | done |
| | B3 | Goal planner: weekly saving needed, with and without interest | 0 |
| | B4 | Portfolio analytics: allocation, concentration, volatility, risk score | 0 |
| C core | C0 | Contract amendment: provider-neutral response state, stop reason, per-call max tokens and effort | 0 |
| | C1 | Adapters: Anthropic and OpenAI, factory by `LLM_PROVIDER`, tool-schema translation | C0 |
| | C2 | LangGraph skeleton: state, router, stub agents, Guardian slot, in-memory trace sink | C0 |
| | C3 | Agent tool loop used inside nodes (tool calls, errors as results, step cap) | C1, C2 |
| K knowledge | K1 | Article format, ingest script, FAISS retriever with attribution, 5 sample articles | 0 |
| | K2 to K4 | Article batches (about 20 each), reviewed by the owner for accuracy | K1 |
| M market | M1 | Provider interface, mock provider, TTL cache | 0 |
| | M2 | yfinance provider (quotes and history), throttle handling, errors | M1 |
| | M3 | Alpha Vantage provider with a daily request budget, and the fallback chain that tries providers in order and reports which one answered | M1, M2, owner's key |
| A data | A1 | Docker Postgres, schema, migrations | Docker installed |
| | A2 | Repositories: kids, profiles, answers, ledger, traces, cache | A1 |
| E agents | E1 | Finance Q&A agent | K1, C3 |
| | E2 | Goal and Game Coach | B1, B2, B3, C3 |
| | E3 | Market Analysis agent | M1, C3 |
| | E4 | Portfolio Analysis agent | B4, M1, C3 |
| | E5 | Tax Education agent | K1, C3 |
| | E6 | Guardian + reject and rewrite loop in the graph | C2, C3 |
| | E7 | Router: real classification, mixed-query handling | E1 to E5 |
| D UI | D1 | Streamlit shell, theme, tabs on fake data | 0 |
| | D2 | Chat tab wired to the graph, session memory | D1, C2 |
| | D3 | Games tab | D1, B1, B2 |
| | D4 | Portfolio and Markets tabs with charts | D1, B4, M1 |
| | D5 | Goals, Knowledge, Parent tabs | D1, B3, K1, A2 |
| X | X2 | Eval suites and report | E7 |
| | X3 | Coverage gate at 90 percent | most code merged |
| | X4 | README, architecture diagram, demo script, final polish | all |

## 14-day schedule

| Days | Parallel work | Milestone |
|---|---|---|
| 1-2 | C0, C1, B3, K1, M1, D1; A1 as soon as Docker works | Adapters run, FAISS answers a question, UI shell renders |
| 3-5 | C2, C3, B4, M2, M3, K2, A2, E1, D2 | First agent answers end to end through LangGraph |
| 6-8 | E2, E3, E4, E5, K3, D3, D4 | All five agents work individually |
| 9-10 | E6, E7, D5 | Router and Guardian loop done |
| 11-12 | X2, X3, K4, UI polish and charts | Coverage at 90, evals run, knowledge base at 60+ |
| 13 | X4 | README, diagram, setup guide |
| 14 | Buffer, demo video (5-10 min) | Submission |

Critical path: C0 to C1 to C3 to the agents. Long pole: knowledge-base content, so K1 and K2 start in week 1.

## Owner tasks (accounts and installs I cannot do)
1. Install Docker Desktop, then verify with `docker run --rm hello-world`.
2. Get an LLM key you can demo with (program OpenAI key, or an Anthropic key). Put it in `.env`, never in chat or git.
3. Get an Alpha Vantage API key (free, can take up to 24 hours) and put it in `.env` as `ALPHAVANTAGE_API_KEY`. yfinance needs no key. Needed by M3, around day 4.
4. Create the public GitHub repo near the end, and share the URL when you want me to prepare the push.

## Risks
- **Content volume:** 60 articles is the long pole. Mitigation: LLM-drafted originals in batches, with your review for accuracy. We do not copy third-party text.
- **Market data reliability:** yfinance is unofficial and Yahoo can throttle or change endpoints, and Alpha Vantage allows only 25 requests a day. Mitigation: provider chain (yfinance, then Alpha Vantage, then saved sample quotes), cache with about 30 minute TTL, a request budget on Alpha Vantage, and a demo mode that never touches the network.
- **Scope:** five agents plus charts in 14 days is tight. If days 9-10 finish early, an MCP server (about one PR, wrapping the existing tools) can be added back for up to 5 points. Cut order if behind: Parent tab, then evals extras, then 60 articles down to 50, never the tests or docs.
- **Child safety:** local only, nickname only, Guardian on every reply, education not advice.
