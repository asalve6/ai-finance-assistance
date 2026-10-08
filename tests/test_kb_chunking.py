from penny.kb.article import KB_DIR, load_articles, parse_article
from penny.kb.chunking import MAX_CHUNK_WORDS, chunk_article, split_sections

ARTICLE = """---
id: piggy-bank-basics
title: Your piggy bank
area: saving
level: starter
summary: A piggy bank keeps money safe.
key_terms: [saving]
sources:
  - {title: CFPB, url: "https://www.consumerfinance.gov/"}
---
Intro line before any heading.

## Why save?

Saving means keeping money. It helps you buy bigger things.

## Try it

Save one dollar today.
"""


def test_split_sections_names_leading_text_overview_and_skips_empty_sections():
    sections = split_sections("Lead.\n\n## One\n\nText one.\n\n## Empty\n\n## Two\n\nText two.")
    assert sections == [("Overview", "Lead."), ("One", "Text one."), ("Two", "Text two.")]


def test_article_becomes_a_summary_chunk_plus_one_chunk_per_section():
    chunks = chunk_article(parse_article(ARTICLE))
    assert [c.heading for c in chunks] == ["Summary", "Overview", "Why save?", "Try it"]
    assert [c.id for c in chunks] == [f"piggy-bank-basics#{n}" for n in range(4)]
    assert chunks[0].text == "A piggy bank keeps money safe."


def test_every_chunk_carries_title_level_and_sources_for_attribution():
    for chunk in chunk_article(parse_article(ARTICLE)):
        assert chunk.title == "Your piggy bank"
        assert chunk.level == "starter"
        assert chunk.sources[0].url == "https://www.consumerfinance.gov/"


def test_embed_text_adds_title_and_heading_context():
    chunk = chunk_article(parse_article(ARTICLE))[2]
    assert chunk.embed_text.startswith("Your piggy bank. Why save?. Saving means")


def test_long_sections_split_on_sentence_boundaries_within_the_limit():
    sentence = "Saving a little money each week is a good habit for everyone."  # 12 words
    long_article = ARTICLE.replace(
        "Saving means keeping money. It helps you buy bigger things.", " ".join([sentence] * 30)
    )
    chunks = [c for c in chunk_article(parse_article(long_article)) if c.heading == "Why save?"]
    assert len(chunks) > 1
    assert all(len(c.text.split()) <= MAX_CHUNK_WORDS for c in chunks)
    assert all(c.text.endswith(".") for c in chunks)
    assert sum(c.text.count(sentence) for c in chunks) == 30


def test_real_articles_chunk_cleanly():
    articles, _ = load_articles(KB_DIR / "articles")
    for _, article in articles:
        chunks = chunk_article(article)
        assert len(chunks) >= 4
        assert len({c.id for c in chunks}) == len(chunks)
        assert chunks[-1].heading == "Try it"
        assert all(c.text.strip() for c in chunks)


# ------------------------------------------------------------------ structure is preserved

STRUCTURED = """---
id: piggy-bank-basics
title: Your piggy bank
area: saving
level: starter
summary: A piggy bank keeps money safe.
key_terms: [saving]
sources:
  - {title: CFPB, url: "https://www.consumerfinance.gov/"}
---
## Ways to save

There are two main ways.

- **Weekly.** Put money in every week.
- **Gifts.** Put in part of any gift.

After that, you can count your money.

## Example

```python
total = 0
total += 5

total += 5
```
"""


def test_lists_and_paragraph_breaks_survive_in_the_chunk_text():
    chunk = next(c for c in chunk_article(parse_article(STRUCTURED)) if c.heading == "Ways to save")
    assert chunk.text == (
        "There are two main ways.\n\n"
        "- **Weekly.** Put money in every week.\n"
        "- **Gifts.** Put in part of any gift.\n\n"
        "After that, you can count your money."
    )


def test_embed_text_is_flattened_to_plain_prose():
    chunk = next(c for c in chunk_article(parse_article(STRUCTURED)) if c.heading == "Ways to save")
    assert chunk.embed_text == (
        "Your piggy bank. Ways to save. There are two main ways. Weekly. Put money in every "
        "week. Gifts. Put in part of any gift. After that, you can count your money."
    )


def test_a_fenced_code_block_keeps_its_lines_and_blank_lines():
    chunk = next(c for c in chunk_article(parse_article(STRUCTURED)) if c.heading == "Example")
    assert chunk.text == "```python\ntotal = 0\ntotal += 5\n\ntotal += 5\n```"
    assert "```" not in chunk.embed_text


def test_a_heading_inside_a_code_block_does_not_start_a_new_section():
    text = STRUCTURED.replace("total = 0", "## not a heading\ntotal = 0")
    headings = [c.heading for c in chunk_article(parse_article(text))]
    assert headings == ["Summary", "Ways to save", "Example"]


def test_an_oversized_code_block_is_never_split():
    code = "```\n" + "\n".join(f"line_{n} = {n}" for n in range(200)) + "\n```"
    text = STRUCTURED.split("## Example")[0] + "## Example\n\n" + code + "\n"
    chunks = [c for c in chunk_article(parse_article(text)) if c.heading == "Example"]
    assert [c.text for c in chunks] == [code]


def test_a_long_list_splits_between_items_never_inside_one():
    items = [f"- Item number {n} is a short sentence about saving money." for n in range(40)]
    text = STRUCTURED.split("## Ways to save")[0] + "## Ways to save\n\n" + "\n".join(items) + "\n"
    chunks = [c for c in chunk_article(parse_article(text)) if c.heading == "Ways to save"]
    assert len(chunks) > 1
    assert all(len(c.text.split()) <= MAX_CHUNK_WORDS for c in chunks)
    assert [line for c in chunks for line in c.text.splitlines()] == items


def test_real_lists_stay_on_separate_lines():
    articles = {a.id: a for _, a in load_articles(KB_DIR / "articles")[0]}
    chunk = next(
        c for c in chunk_article(articles["compound-interest"]) if c.heading.startswith("Where")
    )
    assert "\n- Start: $100.00\n- After year 1: $105.00\n- After year 2: $110.25\n" in chunk.text
