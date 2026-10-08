import numpy as np
import pytest
import yaml

from penny.contracts import Level
from penny.kb import ask, build
from penny.kb.article import KB_DIR, Article, load_articles, parse_article
from penny.kb.embedding import HashingEmbedder, SentenceTransformerEmbedder
from penny.kb.index import IndexMismatchError, KBIndex, content_hash, select_articles
from penny.kb.retriever import retrieve

embedder = HashingEmbedder()

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


def top(index: KBIndex, query: str, **kwargs) -> str | None:
    hits = index.search(query, **kwargs)
    return hits[0].chunk.article_id if hits else None


# ------------------------------------------------------------------ the reviewed-only rule


def test_drafts_are_left_out_unless_asked_for():
    articles = corpus()
    assert [a.id for a in select_articles(articles, include_drafts=False)] == [
        "piggy-bank-basics",
        "what-is-a-stock",
        "what-are-taxes",
    ]
    assert len(select_articles(articles, include_drafts=True)) == 4


def test_a_child_cannot_get_an_answer_from_an_unreviewed_article():
    query = "a bond is a loan to a government that pays interest"
    reviewed_only = KBIndex.build(corpus(), embedder)
    with_drafts = KBIndex.build(corpus(), embedder, include_drafts=True)
    assert top(reviewed_only, query) != "what-is-a-bond"
    assert top(with_drafts, query) == "what-is-a-bond"
    assert "what-is-a-bond" not in {c.article_id for c in reviewed_only.chunks}


# ------------------------------------------------------------------ searching


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("what is a stock and what are shares", "what-is-a-stock"),
        ("why is tax taken from my paycheck", "what-are-taxes"),
        ("how does saving money in a piggy bank help", "piggy-bank-basics"),
    ],
)
def test_search_finds_the_right_article_first(query, expected):
    assert top(KBIndex.build(corpus(), embedder), query) == expected


def test_search_returns_nothing_for_an_off_topic_question():
    index = KBIndex.build(corpus(), embedder)
    assert index.search("quantum chromodynamics lattice gauge") == []
    assert index.search("   ") == []


def test_k_limits_results_and_scores_are_sorted():
    hits = KBIndex.build(corpus(), embedder).search("money", k=2, min_score=0.0)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score


def test_level_filter_hides_harder_articles():
    index = KBIndex.build(corpus(draft_bond=False), embedder)
    query = "a stock is a small piece of ownership in a company"
    assert top(index, query) == "what-is-a-stock"
    assert top(index, query, max_level=Level.STARTER) != "what-is-a-stock"
    assert top(index, query, max_level=Level.SAVER) == "what-is-a-stock"
    bond_query = "a bond is a loan that pays interest until maturity"
    assert top(index, bond_query, max_level=Level.SAVER) != "what-is-a-bond"
    assert top(index, bond_query, max_level=Level.BUILDER) == "what-is-a-bond"


# ------------------------------------------------------------------ saving and staleness


def test_save_and_load_give_identical_results(tmp_path):
    built = KBIndex.build(corpus(), embedder)
    built.save(tmp_path)
    loaded = KBIndex.load(embedder, tmp_path)
    for query in ("what is a stock", "tax on my paycheck", "piggy bank"):
        assert loaded.search(query) == built.search(query)
    assert loaded.meta == built.meta


def test_loading_with_a_different_embedder_is_refused(tmp_path):
    KBIndex.build(corpus(), embedder).save(tmp_path)
    with pytest.raises(IndexMismatchError, match="Rebuild"):
        KBIndex.load(SentenceTransformerEmbedder(model=object()), tmp_path)


def test_index_knows_when_articles_changed_since_it_was_built():
    articles = corpus()
    index = KBIndex.build(articles, embedder)
    assert not index.is_stale(articles)
    edited = [*articles[:-1], article("what-is-a-bond", reviewed=False, body="Changed text here.")]
    assert not index.is_stale(edited)  # the bond is a draft, so it is not in this index
    newly_reviewed = [*articles[:-1], article("what-is-a-bond", reviewed=True)]
    assert index.is_stale(newly_reviewed)
    changed = [article("piggy-bank-basics", body="Different words entirely."), *articles[1:]]
    assert index.is_stale(changed)


def test_content_hash_ignores_order_but_not_content():
    articles = corpus()
    assert content_hash(articles) == content_hash(list(reversed(articles)))
    assert content_hash(articles) != content_hash(articles[:-1])


def test_empty_index_saves_loads_and_returns_nothing(tmp_path):
    index = KBIndex.build([article("what-is-a-bond", reviewed=False)], embedder)
    assert index.meta.chunk_count == 0
    index.save(tmp_path)
    assert KBIndex.load(embedder, tmp_path).search("bond loan") == []


# ------------------------------------------------------------------ the retriever


def test_retrieval_reports_confidence_citations_and_context():
    result = retrieve(KBIndex.build(corpus(), embedder), "what is a stock and what are shares")
    assert result.confident and result.reason == "ok"
    assert result.top_score == result.hits[0].score > 0
    citations = result.citations()
    assert citations[0].article_id == "what-is-a-stock"
    assert [c.article_id for c in citations] == list(dict.fromkeys(c.article_id for c in citations))
    assert citations[0].sources[0].url == "https://example.gov/what-is-a-stock"
    context = result.as_prompt_context()
    assert context.startswith("[what-is-a-stock]")
    assert "ownership in a company" in context


def test_retrieval_explains_why_it_is_not_confident():
    index = KBIndex.build(corpus(), embedder)
    off_topic = retrieve(index, "quantum chromodynamics lattice gauge")
    assert (off_topic.confident, off_topic.reason, off_topic.top_score) == (False, "no_match", 0.0)
    assert off_topic.citations() == [] and off_topic.as_prompt_context() == ""
    empty = retrieve(KBIndex.build([], embedder), "what is a stock")
    assert (empty.confident, empty.reason) == (False, "empty_index")


# ------------------------------------------------------------------ command line


def write_articles(root, articles: list[Article]):
    (root / "articles").mkdir(parents=True)
    for a in articles:
        meta = a.model_dump(mode="json", exclude={"body"})
        (root / "articles" / f"{a.id}.md").write_text(f"---\n{yaml.safe_dump(meta)}---\n{a.body}\n")


def test_build_and_ask_commands_end_to_end(tmp_path, capsys):
    write_articles(tmp_path / "kb", corpus())
    out = tmp_path / "idx"
    args = ["--dir", str(tmp_path / "kb"), "--out", str(out), "--embedder", "hashing"]
    assert build.main(args) == 0
    text = capsys.readouterr().out
    assert "Indexed 3 of 4 articles" in text and "1 unreviewed article(s) left out" in text

    assert ask.main(["what is a stock", "--index", str(out), "--embedder", "hashing"]) == 0
    answer = capsys.readouterr().out
    assert "what-is-a-stock" in answer and "https://example.gov/what-is-a-stock" in answer

    off_topic = ["quantum chromodynamics lattice", "--index", str(out), "--embedder", "hashing"]
    assert ask.main(off_topic) == 0
    assert "Not confident (no_match)" in capsys.readouterr().out


def test_build_warns_when_nothing_is_reviewed_and_supports_drafts(tmp_path, capsys):
    write_articles(tmp_path / "kb", [article("what-is-a-bond", reviewed=False)])
    base = ["--dir", str(tmp_path / "kb"), "--out", str(tmp_path / "i"), "--embedder", "hashing"]
    assert build.main(base) == 0
    assert "index is empty" in capsys.readouterr().out
    assert build.main([*base, "--include-drafts"]) == 0
    assert "Indexed 1 of 1 articles" in capsys.readouterr().out


def test_build_fails_when_there_are_no_articles(tmp_path, capsys):
    (tmp_path / "kb" / "articles").mkdir(parents=True)
    assert build.main(["--dir", str(tmp_path / "kb"), "--embedder", "hashing"]) == 1
    assert "No articles" in capsys.readouterr().out


def test_ask_applies_the_level_filter(tmp_path, capsys):
    write_articles(tmp_path / "kb", corpus(draft_bond=False))
    out = tmp_path / "idx"
    build.main(["--dir", str(tmp_path / "kb"), "--out", str(out), "--embedder", "hashing"])
    capsys.readouterr()
    query = ["a bond is a loan that pays interest", "--index", str(out), "--embedder", "hashing"]
    ask.main([*query, "--level", "starter"])
    assert "Not confident" in capsys.readouterr().out
    ask.main([*query, "--level", "builder"])
    assert "what-is-a-bond" in capsys.readouterr().out


# ------------------------------------------------------------------ the real articles


@pytest.fixture(scope="module")
def real_index() -> KBIndex:
    articles = [a for _, a in load_articles(KB_DIR / "articles")[0]]
    return KBIndex.build(articles, embedder, include_drafts=True)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("what is a stock?", "what-is-a-stock"),
        ("how does compound interest work", "compound-interest"),
        ("why is my first paycheck smaller than I expected", "what-are-taxes"),
        ("what is the difference between a need and a want", "needs-vs-wants"),
        ("how can small habits add up over time", "drop-by-drop"),
    ],
)
def test_real_questions_reach_the_right_article(real_index, query, expected):
    assert top(real_index, query) == expected


def test_real_index_only_contains_reviewed_articles_by_default():
    articles = [a for _, a in load_articles(KB_DIR / "articles")[0]]
    index = KBIndex.build(articles, embedder)
    reviewed = {a.id for a in articles if a.reviewed}
    assert {c.article_id for c in index.chunks} == reviewed


def test_vectors_stay_unit_length_through_the_index(real_index):
    vectors = embedder.embed([c.embed_text for c in real_index.chunks])
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


# ------------------------------------------------------------------ chunking rules and structure


def test_changing_the_chunking_rules_makes_a_saved_index_stale(monkeypatch):
    articles = corpus()
    index = KBIndex.build(articles, embedder)
    assert not index.is_stale(articles)
    monkeypatch.setattr("penny.kb.index.CHUNKER_VERSION", 999)
    assert index.is_stale(articles)


def test_prompt_context_keeps_lists_on_separate_lines(real_index):
    result = retrieve(real_index, "how does compound interest grow after year 2")
    context = result.as_prompt_context()
    assert "\n- Start: $100.00\n- After year 1: $105.00\n- After year 2: $110.25" in context
