# Delivery plan

Working agreement
- One PR = one reviewable idea, target under ~300 changed lines, tests included.
- Branches are named `pr/<nn>-<slug>` and cut from `main`. Nothing is pushed until the owner reviews it.
- Lanes only touch their own package, so merges stay clean. `contracts.py` changes need their own PR.
- Every lane can run without the others: engines are pure, the DB lane has no LLM, agents use `FakeLLM`.

## Dependency graph

```
PR0 scaffold + contracts
 |
 |-- Lane A: data     A1 -> A2 -> A3
 |-- Lane B: engines  B1, B2      (independent of each other)
 |-- Lane C: agent core  C1 -> C2
 |-- Lane D: UI       D1 -> D2, D3, D4
 |
 +-- Integration (needs lanes above)
      E1 Assessor   (A2, C1)
      E2 Coach      (B1, B2, A2, C1)
      E3 Guardian   (C1)  -> E3b retry loop with Coach (E2, E3)
      E4 Orchestrator (E1, E2)
      F1 Evals      (E1-E4)
      G1 Parent view + trace viewer (A2, C2, D1)
      G2 README, architecture diagram, demo script
```

## PR list

| PR | Lane | Scope | Depends on |
|----|------|-------|-----------|
| 0 | - | Scaffold, shared contracts, FakeLLM | - |
| A1 | data | Postgres schema + migration, local setup docs | 0 |
| A2 | data | Repositories: kids, profiles, answers, ledger, traces | A1 |
| A3 | data | Seed script with 25 assessment questions | A1 |
| B1 | engines | Piggy Bank engine + tests | 0 |
| B2 | engines | Lemonade engine + tests | 0 |
| C1 | agent core | Anthropic client, hand-written tool loop, tool schemas | 0 |
| C2 | agent core | TraceSink writing to agent_traces | A2, C1 |
| D1 | UI | Streamlit shell, theme, screens on fake data | 0 |
| D2 | UI | Onboarding screens | D1 |
| D3 | UI | Lemonade game screens | D1 |
| D4 | UI | Rewards screen | D1 |
| E1 | agents | Assessor | A2, C1 |
| E2 | agents | Coach | B1, B2, A2, C1 |
| E3 | agents | Guardian | C1 |
| E3b | agents | Coach to Guardian reject and rewrite loop | E2, E3 |
| E4 | agents | Orchestrator routing | E1, E2 |
| F1 | evals | Five eval suites and a report | E4 |
| G1 | UI | Parent view and trace viewer | A2, C2, D1 |
| G2 | docs | README, diagram, demo script | all |
