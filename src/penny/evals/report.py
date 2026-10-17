"""Write eval results as a Markdown report (for people) and JSON (for comparing runs)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from penny.evals.suites import SuiteResult, rate

REPORT_DIR = Path(__file__).resolve().parents[3] / "docs" / "evals"


def _cell(text: str) -> str:
    """Safe inside a Markdown table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def markdown(suites: Sequence[SuiteResult], setup: dict[str, str], when: datetime) -> str:
    lines = [
        "# Penny eval report",
        "",
        f"Run on {when:%Y-%m-%d %H:%M}. "
        + ", ".join(f"{key}: {value}" for key, value in setup.items())
        + ".",
        "",
        "Regenerate with `make evals`. Cases live in `data/evals/`.",
        "",
        "## Summary",
        "",
        "| Suite | Passed | Key numbers |",
        "|---|---|---|",
    ]
    for suite in suites:
        numbers = "; ".join(f"{k}: {v}" for k, v in suite.metrics.items())
        skipped = f" ({suite.skipped} skipped)" if suite.skipped else ""
        lines.append(
            f"| {suite.name} | {rate(suite.passed, suite.total)}{skipped} | {_cell(numbers)} |"
        )
    for suite in suites:
        lines += [
            "",
            f"## {suite.name.capitalize()}",
            "",
            "| Case | Result | Detail | ms |",
            "|---|---|---|---|",
        ]
        for r in suite.results:
            mark = "skip" if r.passed is None else ("pass" if r.passed else "**FAIL**")
            lines.append(f"| {r.id} | {mark} | {_cell(r.detail)} | {r.latency_ms or ''} |")
    return "\n".join(lines) + "\n"


def to_json(suites: Sequence[SuiteResult], setup: dict[str, str], when: datetime) -> str:
    data = {
        "run_at": when.isoformat(timespec="seconds"),
        "setup": setup,
        "suites": [
            {
                "name": s.name,
                "passed": s.passed,
                "total": s.total,
                "skipped": s.skipped,
                "metrics": s.metrics,
                "results": [r.model_dump() for r in s.results],
            }
            for s in suites
        ],
    }
    return json.dumps(data, indent=2) + "\n"


def write(
    suites: Sequence[SuiteResult],
    setup: dict[str, str],
    when: datetime,
    directory: Path = REPORT_DIR,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    md_path, json_path = directory / "report.md", directory / "report.json"
    md_path.write_text(markdown(suites, setup, when))
    json_path.write_text(to_json(suites, setup, when))
    return md_path, json_path
