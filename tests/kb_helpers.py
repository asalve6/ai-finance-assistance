"""Shared synthetic knowledge-base articles for tests."""

import yaml

from penny.kb.article import Article, parse_article

BODIES = {
    "piggy-bank-basics": (
        "saving",
        "starter",
        "A piggy bank keeps your money safe.",
        "Saving money in a piggy bank helps you buy bigger things later, like a bike.\n\n"
        "## Try it\n\nPut one dollar in your piggy bank today.",
    ),
    "what-is-a-stock": (
        "markets",
        "saver",
        "A stock is a small piece of a company.",
        "A stock is a small piece of ownership in a company. People who own shares are called "
        "shareholders. Some companies pay dividends to shareholders.\n\n"
        "## Try it\n\nLook up the share price of a company you know.",
    ),
    "what-are-taxes": (
        "taxes",
        "starter",
        "Taxes fund shared services.",
        "Taxes are money paid to the government. Income tax is taken from your paycheck, and "
        "sales tax is added at the store.\n\n## Try it\n\nFind the tax line on a receipt.",
    ),
    "what-is-a-bond": (
        "markets",
        "builder",
        "A bond is a loan.",
        "A bond is a loan you make to a company or government. It pays interest until the "
        "maturity date.\n\n## Try it\n\nName one thing a government might borrow for.",
    ),
}


def article(article_id: str, *, reviewed: bool = True, body: str | None = None) -> Article:
    area, level, summary, text = BODIES[article_id]
    meta = {
        "id": article_id,
        "title": article_id.replace("-", " ").title(),
        "area": area,
        "level": level,
        "summary": summary,
        "key_terms": ["x"],
        "sources": [{"title": "Gov", "url": f"https://example.gov/{article_id}"}],
        "reviewed": reviewed,
    }
    return parse_article(f"---\n{yaml.safe_dump(meta)}---\n{body or text}\n")


def corpus(*, draft_bond: bool = True) -> list[Article]:
    return [
        article("piggy-bank-basics"),
        article("what-is-a-stock"),
        article("what-are-taxes"),
        article("what-is-a-bond", reviewed=not draft_bond),
    ]


def write_articles(root, articles: list[Article]):
    (root / "articles").mkdir(parents=True)
    for a in articles:
        meta = a.model_dump(mode="json", exclude={"body"})
        (root / "articles" / f"{a.id}.md").write_text(f"---\n{yaml.safe_dump(meta)}---\n{a.body}\n")
