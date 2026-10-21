# Knowledge base guide

74 planned original, kid-level articles: 64 on money topics, 4 on money mindset (see PHILOSOPHY.md) and 6 "word bank" articles of short definitions. They power the Finance Q&A and Tax Education agents (RAG), and every answer shows the article it came from.

## Where things live

| Path | What |
|---|---|
| `data/kb/topics.yaml` | The 74 planned topics: id, title, area, level |
| `data/kb/articles/<id>.md` | One article per topic. File name must equal the id |
| `src/penny/kb/` | Parsing and checks (retrieval comes in a later PR) |

## Article format

```
---
id: piggy-bank-basics            # same as the file name and a topics.yaml entry
title: "Your piggy bank: where saving starts"
area: saving                     # saving|interest|earning|budgeting|markets|risk|companies|taxes|safety|mindset
level: starter                   # starter|saver|builder (must match topics.yaml)
summary: One sentence, 160 characters or fewer.
key_terms: [saving, goal]        # 1 to 6
sources:                         # at least one public https page the facts came from
  - title: CFPB, Youth financial education
    url: https://www.consumerfinance.gov/...
reviewed: false                  # the owner flips this to true after review
---
Body in markdown, 200 to 450 words, with a final "## Try it" section.
```

## Word bank articles

The `words-*` articles (banking, investing, borrowing, earning, shopping, money safety) hold short
definitions, one term per `##` heading. Search splits articles at headings, so each term is found
on its own. To add a term, add a heading and two or three sentences to the right word bank, keep
the article within the word limit, and start a new word bank when one gets full.

## Writing rules
- Original wording at about a grade 6 reading level. Facts come from public sources (US government sites are the preferred ones). Never copy text from other sites.
- Education, not advice. No "you should buy", no promises, no named stock picks.
- Avoid numbers that go stale. If one is needed, label it as an example or add `as_of`.
- Short sentences, concrete examples, one idea per section.

## Checking

```bash
make kb-check      # format, word count, reading grade, advice wording, coverage table
make kb-links      # also confirms every source url responds (needs network)
```

The reading grade is an estimate (Flesch-Kincaid with a simple syllable counter). It catches text that is too hard but is not a substitute for a human read.

## Searching (RAG)

Articles are split into chunks (a summary plus one per section), embedded, and stored in a FAISS index under `data/kb/index/` (not committed). Each result carries its article and sources, so answers can cite them.

**Only reviewed articles are indexed** by default, so a child never gets an answer from an article you have not checked.

```bash
make kb-index-dev                          # offline test index: word matching, includes drafts, no key
make kb-ask Q="what is a stock?" EMB=hashing

# Real index. Needs OPENAI_API_KEY in .env (see .env.example):
make kb-index                              # OpenAI text-embedding-3-small, reviewed articles only
make kb-ask Q="why is my paycheck smaller?"
```

**Privacy note:** with OpenAI embeddings, each question a child types is sent to OpenAI to be embedded, and the article text is sent once when the index is built. No names or personal details are stored or sent.

The default embedder is `openai` (set `KB_EMBEDDER` in `.env` to change it). `hashing` is for tests and offline work, and `minilm` is an optional local model (`uv sync --extra embeddings`).

If nothing scores above the embedder's threshold, the result is "not confident" and the agent must say it does not know. The threshold (0.30) is provisional and has to be calibrated on real questions, because every embedding model produces scores on its own scale.

## Owner review checklist (about 5 minutes per article)
1. Are the facts correct?
2. Would a 12-year-old follow it? (Even better: have your son read a few.)
3. Is it education, with no advice or promises?
4. Does the example make sense and the arithmetic work?
5. Are the sources real and relevant?

Then set `reviewed: true` in the front matter. The checker lists unreviewed articles as warnings and shows reviewed counts per area.
