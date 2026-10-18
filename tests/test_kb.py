import io
import urllib.error
from pathlib import Path

import pytest
import yaml

from penny.contracts import Level
from penny.kb import __main__ as cli
from penny.kb.article import (
    KB_DIR,
    Area,
    ArticleError,
    Source,
    Topic,
    load_articles,
    load_topics,
    parse_article,
)
from penny.kb.checks import (
    check_all,
    check_article,
    check_links,
    coverage,
    reading_grade,
    word_count,
)

BODY = "Saving money is a good habit for kids. " * 30 + "\n\n## Try it\n\nSave one dollar today."


def make_text(**overrides: object) -> str:
    meta = {
        "id": "piggy-bank-basics",
        "title": "Your piggy bank",
        "area": "saving",
        "level": "starter",
        "summary": "A piggy bank keeps money safe.",
        "key_terms": ["saving"],
        "sources": [{"title": "CFPB", "url": "https://www.consumerfinance.gov/"}],
        "reviewed": True,
    }
    body = str(overrides.pop("body", BODY))
    meta.update(overrides)
    return f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n{body}\n"


TOPICS = {
    "piggy-bank-basics": Topic(
        id="piggy-bank-basics", title="Piggy", area=Area.SAVING, level=Level.STARTER
    )
}


def errors(text: str, stem: str = "piggy-bank-basics") -> list[str]:
    issues = check_article(parse_article(text), stem, TOPICS)
    return [i.message for i in issues if i.severity == "error"]


# ------------------------------------------------------------------ parsing


def test_parse_valid_article():
    article = parse_article(make_text())
    assert article.id == "piggy-bank-basics"
    assert article.level is Level.STARTER
    assert article.sources[0].url.startswith("https://")
    assert article.body.startswith("Saving money")


@pytest.mark.parametrize(
    "text",
    [
        "no front matter here",
        "---\nid: [unclosed\n---\nbody",
        "---\n- just\n- a list\n---\nbody",
        "---\nid: only-an-id\n---\nbody",
    ],
)
def test_parse_rejects_bad_files(text):
    with pytest.raises(ArticleError):
        parse_article(text)


# ------------------------------------------------------------------ checks


def test_clean_article_has_no_issues():
    assert check_article(parse_article(make_text()), "piggy-bank-basics", TOPICS) == []


def test_unreviewed_is_only_a_warning():
    issues = check_article(parse_article(make_text(reviewed=False)), "piggy-bank-basics", TOPICS)
    assert [i.severity for i in issues] == ["warning"]


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"sources": []}, "at least one source"),
        ({"sources": [{"title": "x", "url": "http://insecure.example"}]}, "https://"),
        ({"key_terms": []}, "key_terms"),
        ({"summary": "x" * 161}, "160"),
        ({"area": "taxes"}, "area"),
        ({"level": "builder"}, "level"),
        ({"body": "Too short.\n\n## Try it\n\nGo."}, "words"),
        ({"body": "Saving money is a good habit for kids. " * 30}, "Try it"),
        ({"body": BODY + "\n\nYou should buy this stock."}, "you should buy"),
        ({"body": BODY + "\n\nThis is GUARANTEED to work."}, "guaranteed"),
    ],
)
def test_rules_each_produce_an_error(overrides, fragment):
    messages = errors(make_text(**overrides))
    assert any(fragment in m for m in messages), messages


def test_id_must_match_file_name_and_topic_list():
    assert any("file name" in m for m in errors(make_text(), stem="other-name"))
    unknown = errors(make_text(id="not-planned"), stem="not-planned")
    assert any("topics.yaml" in m for m in unknown)


def test_very_hard_text_is_rejected_for_reading_level():
    hard = "Notwithstanding considerable macroeconomic uncertainty, institutional investors " * 40
    messages = errors(make_text(body=hard + "\n\n## Try it\n\nRead."))
    assert any("reading grade" in m for m in messages)


def test_slightly_hard_text_is_only_a_warning():
    # Measured grade is about 8.4: above the 7.5 target but below the 9.5 limit.
    middling = (
        "Banks pay interest on your savings, and that interest grows slowly over many years. "
    )
    text = make_text(body=middling * 20 + "\n\n## Try it\n\nRead.")
    issues = check_article(parse_article(text), "piggy-bank-basics", TOPICS)
    grade_issues = [i for i in issues if "grade" in i.message]
    assert [i.severity for i in grade_issues] == ["warning"]


def test_reading_grade_orders_simple_below_complex_and_handles_empty():
    simple = "The cat sat. The dog ran. We like to play."
    complex_ = "Macroeconomic fluctuations notwithstanding, institutional diversification matters."
    assert reading_grade(simple) < reading_grade(complex_)
    assert reading_grade("") == 0.0


def test_word_count_ignores_markdown_markers():
    assert word_count("## Heading\n\n- **bold** item\n- plain item") == 5


def test_check_all_flags_duplicates():
    one = parse_article(make_text())
    issues = check_all(
        [(Path("a/piggy-bank-basics.md"), one), (Path("b/piggy-bank-basics.md"), one)],
        list(TOPICS.values()),
    )
    assert any("used by 2 files" in i.message for i in issues)
    dup_topics = check_all([], [TOPICS["piggy-bank-basics"], TOPICS["piggy-bank-basics"]])
    assert any("duplicate topic" in i.message for i in dup_topics)


def test_coverage_counts_drafted_and_reviewed_per_area():
    topics = [
        Topic(id="a", title="A", area=Area.SAVING, level=Level.STARTER),
        Topic(id="b", title="B", area=Area.SAVING, level=Level.STARTER),
        Topic(id="c", title="C", area=Area.TAXES, level=Level.STARTER),
    ]
    drafted = parse_article(make_text(id="a", reviewed=True))
    report = coverage([(Path("a.md"), drafted)], topics)
    assert report["saving"] == {"planned": 2, "drafted": 1, "reviewed": 1}
    assert report["taxes"] == {"planned": 1, "drafted": 0, "reviewed": 0}
    assert report["markets"]["planned"] == 0


def test_check_links_fetches_each_url_once_and_flags_non_200():
    a = parse_article(make_text())
    b = parse_article(
        make_text(id="b", sources=[{"title": "dead", "url": "https://dead.example/x"}])
    )
    b2 = parse_article(make_text(id="c", sources=[{"title": "dead", "url": "https://dead.example/x"}]))
    seen: list[str] = []

    def fetch(url: str) -> int:
        seen.append(url)
        return 404 if "dead" in url else 200

    issues = check_links([(Path("a.md"), a), (Path("b.md"), b), (Path("c.md"), b2)], fetch)
    assert len(seen) == 2
    assert [i.where for i in issues] == ["b", "c"]
    assert all("404" in i.message for i in issues)


# ------------------------------------------------------------------ loading and CLI


def write_kb(root: Path, article_text: str | None) -> Path:
    (root / "articles").mkdir(parents=True)
    (root / "topics.yaml").write_text(
        "- {id: piggy-bank-basics, title: Piggy, area: saving, level: starter}\n"
    )
    if article_text is not None:
        (root / "articles" / "piggy-bank-basics.md").write_text(article_text)
    return root


def test_load_articles_reports_files_that_fail_to_parse(tmp_path):
    kb = write_kb(tmp_path, "not an article")
    parsed, failed = load_articles(kb / "articles")
    assert parsed == [] and len(failed) == 1
    assert "front matter" in failed[0][1]


def test_cli_exit_codes_and_report(tmp_path, capsys):
    good = write_kb(tmp_path / "good", make_text())
    assert cli.main(["--dir", str(good)]) == 0
    assert "total" in capsys.readouterr().out

    bad = write_kb(tmp_path / "bad", make_text(sources=[]))
    assert cli.main(["--dir", str(bad)]) == 1
    assert "ERROR" in capsys.readouterr().out


def test_cli_links_flag_uses_the_fetcher(tmp_path, monkeypatch, capsys):
    kb = write_kb(tmp_path, make_text())
    monkeypatch.setattr(cli, "fetch_status", lambda url: 500)
    assert cli.main(["--dir", str(kb), "--links"]) == 0  # link problems are warnings
    assert "source returned 500" in capsys.readouterr().out


def test_fetch_status_maps_success_http_errors_and_network_failures(monkeypatch):
    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *a, **k: Response())
    assert cli.fetch_status("https://ok.example") == 200

    def not_found(*a, **k):
        raise urllib.error.HTTPError("u", 404, "nf", {}, None)

    monkeypatch.setattr(cli.urllib.request, "urlopen", not_found)
    assert cli.fetch_status("https://x.example") == 404

    def down(*a, **k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(cli.urllib.request, "urlopen", down)
    assert cli.fetch_status("https://x.example") == -1


def test_fetch_status_retries_with_a_browser_user_agent_when_blocked(monkeypatch):
    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def picky(request, timeout):
        if request.get_header("User-agent"):  # only the browser-style attempt gets through
            return Response()
        raise urllib.error.HTTPError(request.full_url, 403, "blocked", {}, None)

    monkeypatch.setattr(cli.urllib.request, "urlopen", picky)
    assert cli.fetch_status("https://picky.example") == 200

    def always_blocked(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "blocked", {}, None)

    monkeypatch.setattr(cli.urllib.request, "urlopen", always_blocked)
    assert cli.fetch_status("https://blocked.example") == 403


# ------------------------------------------------------------------ the real data


def test_topic_manifest_has_68_unique_topics_in_the_planned_split():
    topics = load_topics(KB_DIR / "topics.yaml")
    assert len(topics) == 68
    assert len({t.id for t in topics}) == 68
    by_area = {a: sum(1 for t in topics if t.area == a) for a in Area}
    assert by_area == {
        Area.SAVING: 8,
        Area.INTEREST: 7,
        Area.EARNING: 8,
        Area.BUDGETING: 6,
        Area.MARKETS: 11,
        Area.RISK: 7,
        Area.COMPANIES: 4,
        Area.TAXES: 8,
        Area.SAFETY: 5,
        Area.MINDSET: 4,
    }


def test_every_real_article_passes_all_checks():
    topics = load_topics(KB_DIR / "topics.yaml")
    articles, failed = load_articles(KB_DIR / "articles")
    assert failed == []
    assert len(articles) >= 5
    problems = [i for i in check_all(articles, topics) if i.severity == "error"]
    assert problems == []


def test_source_model_requires_title_and_url():
    assert Source(title="t", url="https://x.example").url == "https://x.example"
