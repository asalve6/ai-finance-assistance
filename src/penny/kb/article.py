"""Knowledge-base articles: the file format, parsing and loading.

An article is a markdown file with YAML front matter between two `---` lines, then the body.
`data/kb/topics.yaml` lists every planned topic, so coverage can be tracked.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from penny.contracts import Level

KB_DIR = Path(__file__).resolve().parents[3] / "data" / "kb"


class Area(StrEnum):
    SAVING = "saving"
    INTEREST = "interest"
    EARNING = "earning"
    BUDGETING = "budgeting"
    MARKETS = "markets"
    RISK = "risk"
    COMPANIES = "companies"
    TAXES = "taxes"
    SAFETY = "safety"
    MINDSET = "mindset"


class Source(BaseModel):
    title: str
    url: str


class Topic(BaseModel):
    id: str
    title: str
    area: Area
    level: Level


class Article(BaseModel):
    id: str
    title: str
    area: Area
    level: Level
    summary: str
    key_terms: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    as_of: date | None = None
    reviewed: bool = False
    body: str


class ArticleError(ValueError):
    """An article file that cannot be parsed."""


_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def parse_article(text: str, source: str = "<string>") -> Article:
    match = _FRONT_MATTER.match(text)
    if not match:
        raise ArticleError(f"{source}: missing front matter between --- lines")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ArticleError(f"{source}: front matter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise ArticleError(f"{source}: front matter must be a mapping")
    try:
        return Article.model_validate({**meta, "body": match.group(2).strip()})
    except ValidationError as exc:
        raise ArticleError(f"{source}: {exc}") from exc


def load_topics(path: Path) -> list[Topic]:
    return [Topic.model_validate(item) for item in yaml.safe_load(path.read_text())]


def load_articles(directory: Path) -> tuple[list[tuple[Path, Article]], list[tuple[Path, str]]]:
    """Returns (parsed articles, files that failed to parse with the reason)."""
    parsed: list[tuple[Path, Article]] = []
    failed: list[tuple[Path, str]] = []
    for path in sorted(directory.glob("*.md")):
        try:
            parsed.append((path, parse_article(path.read_text(), str(path))))
        except ArticleError as exc:
            failed.append((path, str(exc)))
    return parsed, failed
