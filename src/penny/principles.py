"""Penny's principles, loaded from data/principles.yaml, and the prompt block built from them."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

PRINCIPLES_PATH = Path(__file__).resolve().parents[2] / "data" / "principles.yaml"


class Principle(BaseModel):
    id: str
    name: str
    summary: str
    voice: str


def load_principles(path: Path = PRINCIPLES_PATH) -> list[Principle]:
    return [Principle.model_validate(item) for item in yaml.safe_load(path.read_text())]


def voice_block(principles: list[Principle] | None = None) -> str:
    """The values section for an agent's system prompt."""
    principles = principles if principles is not None else load_principles()
    lines = ["Penny's values. Let them shape your tone and your examples:"]
    lines += [f"- {p.name}: {p.summary} {p.voice}" for p in principles]
    return "\n".join(lines)
