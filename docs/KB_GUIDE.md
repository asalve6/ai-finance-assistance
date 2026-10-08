# Knowledge base guide

60 original, kid-level articles. They power the Finance Q&A and Tax Education agents (RAG), and every answer shows the article it came from.

## Where things live

| Path | What |
|---|---|
| `data/kb/topics.yaml` | The 60 planned topics: id, title, area, level |
| `data/kb/articles/<id>.md` | One article per topic. File name must equal the id |
| `src/penny/kb/` | Parsing and checks (retrieval comes in a later PR) |

## Article format

```
---
id: piggy-bank-basics            # same as the file name and a topics.yaml entry
title: "Your piggy bank: where saving starts"
area: saving                     # saving|interest|earning|budgeting|markets|risk|companies|taxes|safety
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

## Owner review checklist (about 5 minutes per article)
1. Are the facts correct?
2. Would a 12-year-old follow it? (Even better: have your son read a few.)
3. Is it education, with no advice or promises?
4. Does the example make sense and the arithmetic work?
5. Are the sources real and relevant?

Then set `reviewed: true` in the front matter. The checker lists unreviewed articles as warnings and shows reviewed counts per area.
