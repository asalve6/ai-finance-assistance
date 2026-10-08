"""Command line: `python -m penny.kb [--links]` checks every article and prints coverage."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from pathlib import Path

from penny.kb.article import KB_DIR, load_articles, load_topics
from penny.kb.checks import Issue, check_all, check_links, coverage

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _status_with(url: str, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError):
        return -1


def fetch_status(url: str) -> int:
    """HTTP status of a url. Some government sites block either the default or a browser-style
    user agent, so try both and report the best result."""
    status = _status_with(url, {})
    if status == 200:
        return status
    retry = _status_with(url, {"User-Agent": _USER_AGENT})
    return 200 if retry == 200 else status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m penny.kb")
    parser.add_argument("--dir", type=Path, default=KB_DIR, help="knowledge-base folder")
    parser.add_argument("--links", action="store_true", help="also check that source urls respond")
    args = parser.parse_args(argv)

    topics = load_topics(args.dir / "topics.yaml")
    articles, failed = load_articles(args.dir / "articles")
    issues = [Issue("error", str(path), reason) for path, reason in failed]
    issues += check_all(articles, topics)
    if args.links:
        issues += check_links(articles, fetch_status)

    for issue in sorted(issues, key=lambda i: (i.severity != "error", i.where)):
        print(f"{issue.severity.upper():7} {issue.where}: {issue.message}")

    print("\nCoverage (drafted / reviewed / planned)")
    total = {"planned": 0, "drafted": 0, "reviewed": 0}
    for area, row in coverage(articles, topics).items():
        print(f"  {area:10} {row['drafted']:3} / {row['reviewed']:3} / {row['planned']:3}")
        for key in total:
            total[key] += row[key]
    print(f"  {'total':10} {total['drafted']:3} / {total['reviewed']:3} / {total['planned']:3}")

    errors = sum(1 for i in issues if i.severity == "error")
    print(f"\n{errors} error(s), {len(issues) - errors} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
