"""Environment configuration. Keys live in `.env` (never committed), see `.env.example`."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None) -> bool:
    """Load `.env` from the project root (or `path`). Real environment variables always win."""
    return load_dotenv(path or PROJECT_ROOT / ".env", override=False)
