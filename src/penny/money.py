"""Money formatting shared by the agents and the app. All amounts are whole cents."""

from __future__ import annotations


def dollars(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:.2f}"
