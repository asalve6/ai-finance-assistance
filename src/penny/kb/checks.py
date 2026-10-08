"""Quality checks for knowledge-base articles.

Pure functions. The only network access is through a fetcher you pass to `check_links`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from penny.kb.article import Area, Article, Topic

MIN_WORDS, MAX_WORDS = 200, 450
WARN_GRADE, MAX_GRADE = 7.5, 9.5
TRY_IT_HEADING = "## Try it"

# Phrases that turn education into advice or a promise. Matched case-insensitively.
BANNED_PHRASES = [
    "you should buy",
    "you should sell",
    "you should invest in",
    "i recommend",
    "guaranteed",
    "can't lose",
    "cannot lose",
    "risk-free",
    "get rich",
    "will go up",
    "will go down",
    "best stock",
    "sure thing",
]


@dataclass(frozen=True)
class Issue:
    severity: Literal["error", "warning"]
    where: str
    message: str


def _syllables(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(count, 1)


def _plain_text(markdown: str) -> str:
    """Strip markdown and make every heading or bullet its own sentence."""
    lines = []
    for raw in markdown.splitlines():
        line = re.sub(r"^\s*(#+|[-*]|\d+\.)\s*", "", raw).replace("**", "").strip()
        if not line:
            continue
        lines.append(line if line[-1] in ".!?:" else line + ".")
    return " ".join(lines)


def word_count(markdown: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'$%-]+", _plain_text(markdown)))


def reading_grade(markdown: str) -> float:
    """Flesch-Kincaid grade level, using a simple syllable estimate."""
    text = _plain_text(markdown)
    words = re.findall(r"[A-Za-z']+", text)
    sentences = [s for s in re.split(r"[.!?:]+\s", text + " ") if s.strip()]
    if not words or not sentences:
        return 0.0
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * len(words) / len(sentences) + 11.8 * syllables / len(words) - 15.59


def check_article(article: Article, file_stem: str, topics: dict[str, Topic]) -> list[Issue]:
    where = article.id
    issues: list[Issue] = []

    def error(message: str) -> None:
        issues.append(Issue("error", where, message))

    def warn(message: str) -> None:
        issues.append(Issue("warning", where, message))

    if article.id != file_stem:
        error(f"id '{article.id}' must match the file name '{file_stem}.md'")
    topic = topics.get(article.id)
    if topic is None:
        error("id is not in data/kb/topics.yaml")
    else:
        if topic.area != article.area:
            error(f"area '{article.area}' differs from topics.yaml '{topic.area}'")
        if topic.level != article.level:
            error(f"level '{article.level}' differs from topics.yaml '{topic.level}'")

    if not article.sources:
        error("needs at least one source")
    for source in article.sources:
        if not source.url.startswith("https://"):
            error(f"source url must start with https://: {source.url}")
    if not 1 <= len(article.key_terms) <= 6:
        error("key_terms must list 1 to 6 terms")
    if len(article.summary) > 160:
        error("summary must be 160 characters or fewer")

    words = word_count(article.body)
    if not MIN_WORDS <= words <= MAX_WORDS:
        error(f"body has {words} words, expected {MIN_WORDS} to {MAX_WORDS}")
    if TRY_IT_HEADING not in article.body:
        error(f"body needs a '{TRY_IT_HEADING}' section")

    lowered = article.body.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            error(f"contains advice or promise wording: '{phrase}'")

    grade = reading_grade(article.body)
    if grade > MAX_GRADE:
        error(f"reading grade {grade:.1f} is above {MAX_GRADE}")
    elif grade > WARN_GRADE:
        warn(f"reading grade {grade:.1f} is above the {WARN_GRADE} target")

    if not article.reviewed:
        warn("not yet reviewed by the owner")
    return issues


def check_all(articles: list[tuple[Path, Article]], topics: list[Topic]) -> list[Issue]:
    by_id = {t.id: t for t in topics}
    issues: list[Issue] = []
    if len(by_id) != len(topics):
        issues.append(Issue("error", "topics.yaml", "duplicate topic ids"))
    for path, article in articles:
        issues.extend(check_article(article, path.stem, by_id))
    for article_id, count in Counter(a.id for _, a in articles).items():
        if count > 1:
            issues.append(Issue("error", article_id, f"id used by {count} files"))
    return issues


def coverage(
    articles: list[tuple[Path, Article]], topics: list[Topic]
) -> dict[str, dict[str, int]]:
    """Per area: planned topics, drafted articles and reviewed articles."""
    by_id = {a.id: a for _, a in articles}
    report = {area.value: {"planned": 0, "drafted": 0, "reviewed": 0} for area in Area}
    for topic in topics:
        row = report[topic.area.value]
        row["planned"] += 1
        article = by_id.get(topic.id)
        if article:
            row["drafted"] += 1
            row["reviewed"] += int(article.reviewed)
    return report


def check_links(articles: list[tuple[Path, Article]], fetch: Callable[[str], int]) -> list[Issue]:
    """`fetch` returns an HTTP status (or -1 on network failure). Each url is fetched once."""
    issues: list[Issue] = []
    seen: dict[str, int] = {}
    for _, article in articles:
        for source in article.sources:
            if source.url not in seen:
                seen[source.url] = fetch(source.url)
            status = seen[source.url]
            if status != 200:
                message = f"source returned {status}: {source.url}"
                issues.append(Issue("warning", article.id, message))
    return issues
