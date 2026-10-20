# Demo script (about 7 minutes)

A walk-through for the 5 to 10 minute capstone video. Every question below is also an eval case, so
it is known to work. Times are rough targets.

## Before recording

1. `.env` has `LLM_PROVIDER` and that provider's key, plus `OPENAI_API_KEY` for search.
2. `make kb-index` has been run since the last article change, and the Chat tab shows no
   "Offline demo" notice.
3. Restart the app (`make run`) so it loads the latest index. Streamlit keeps the old one until then.
4. Ask one warm-up question off camera, so prices are cached and the first answer is quick.
5. Set the browser to about 1440 px wide, so the portfolio metrics sit on one row.

If something fails on camera, Penny's safe fallback is part of the story: point to the trace and
say the Guardian would rather show nothing than something unchecked.

## 1. The idea (0:00 to 0:40)

"Penny is a money coach for kids, built for my 12-year-old. It is a multi-agent app on LangGraph:
a router picks one of five specialist agents, and an independent Guardian checks every reply before
a child sees it. Penny teaches; it never gives advice."

Show the README architecture diagram for a few seconds.

## 2. Setup (0:40 to 1:10)

Type a nickname, answer the three quiz questions correctly, start. Point out that the quiz, scored
in code, set the level to builder, and that only a nickname is stored.

## 3. Chat: grounded answers (1:10 to 2:40)

1. Click **"What is a stock?"**. Open **Sources**: the article and the government pages behind it.
   Open **How Penny answered**: router, article search, draft, Guardian approval, with timings.
2. Type **"what is a bond?"**. A different article, cited the same way.
3. Type **"Why is my first paycheck smaller?"**. Routed to the Tax agent, with its "for learning,
   not tax advice" note.
4. Type **"Should I buy Tesla stock?"**. Penny explains risk and declines to advise. Say: buy and
   sell questions are routed to Finance Q&A on purpose, so the answer is grounded in the stock
   article.

## 4. Chat: tools, live data and two-part questions (2:40 to 4:00)

1. **"I want a $60 game in 8 weeks. How much per week?"**: the Coach calls the goal planner tool
   and says $7.50. Show the tool call in the trace: the model never does the maths.
2. **"How much is Disney stock today?"**: the Market agent, with the live price and its source.
3. **"what about Nike?"**: a follow-up; the router uses the earlier turn.
4. **"What is Disney's price, and how do I save for a bike?"**: Penny answers the price, then shows
   an **Also ask** button for the bike part. Click it: the Coach asks for the bike's price.

## 5. Play (4:00 to 4:50)

Play one Lemonade Stand day: read the day's weather, set a price and cups, and show the profit
chart.
Optionally one Piggy Bank week. Say: the games are plain Python engines, and the Coach uses the same
engines as tools, so its numbers always match the game.

## 6. Portfolio and Markets (4:50 to 5:50)

1. Show the starter practice portfolio: worth today, biggest share, bumpiness, and the allocation
   chart. "Prices from Yahoo Finance."
2. Look up Roblox on the right: price, change and the 30-day chart.
3. Back in Chat: **"Is my portfolio spread out?"**, then **"What if I added 4 shares of Roblox to my
   portfolio?"**. The Portfolio agent runs the analytics on the child's own holdings.

## 7. Goals (5:50 to 6:20)

Pick the bike goal, move the weeks slider, turn on interest. The weekly amount and chart update.
Show the family challenge question: Penny's "together" idea.

## 8. Engineering (6:20 to 7:00)

Show `docs/evals/report.md`: routing 42/42, every planted bad draft caught, every whole answer
approved. Run `make cov` in a terminal: 818 tests, 99% coverage. Close with one line on the
roadmap: saved progress in Postgres, a parent view, a weekly news explainer.
