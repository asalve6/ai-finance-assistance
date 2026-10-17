"""Portfolio analytics for a practice portfolio: what each holding is worth, how spread out the
money is, and how bumpy the prices have been. Pure maths, no prices are fetched here.

Kept deliberately simple so every number can be explained to a child:

- **Weight**: each holding's share of the total value.
- **Spread**: from the largest weight. Half or more in one company is "concentrated".
- **Effective number of companies**: 1 divided by the sum of squared weights. Three equal
  holdings give 3; one big holding and two tiny ones give close to 1.
- **Bumpiness**: the typical size of a daily price move (standard deviation of daily returns),
  averaged across holdings by weight. It ignores how holdings move together, which is fine for a
  first lesson and is said so in the explanation.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

Spread = Literal["Concentrated", "Somewhat spread", "Spread out"]
Bumpiness = Literal["Calmer", "Medium", "Bumpier", "Unknown"]

CONCENTRATED_AT_PCT = 50.0
SOMEWHAT_SPREAD_AT_PCT = 35.0
CALMER_BELOW_PCT = 1.0  # typical daily move
BUMPIER_FROM_PCT = 2.0


class Holding(BaseModel):
    symbol: str = Field(min_length=1)
    shares: int = Field(gt=0)
    price_cents: int = Field(gt=0)


class Position(BaseModel):
    symbol: str
    shares: int
    value_cents: int
    weight_pct: float
    daily_move_pct: float | None  # None when there is not enough price history


class PortfolioReport(BaseModel):
    total_cents: int
    positions: list[Position]  # largest first
    largest_weight_pct: float
    effective_holdings: float
    spread: Spread
    daily_move_pct: float | None
    bumpiness: Bumpiness


def daily_move_pct(closes: list[int]) -> float | None:
    """Standard deviation of day-to-day percentage changes. Needs at least three prices."""
    if len(closes) < 3 or any(c <= 0 for c in closes):
        return None
    returns = [(b - a) / a * 100 for a, b in zip(closes, closes[1:], strict=False)]
    mean = sum(returns) / len(returns)
    return math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))


def spread_for(largest_weight_pct: float, holdings: int) -> Spread:
    if holdings == 1 or largest_weight_pct >= CONCENTRATED_AT_PCT:
        return "Concentrated"
    if largest_weight_pct >= SOMEWHAT_SPREAD_AT_PCT:
        return "Somewhat spread"
    return "Spread out"


def bumpiness_for(move_pct: float | None) -> Bumpiness:
    if move_pct is None:
        return "Unknown"
    if move_pct < CALMER_BELOW_PCT:
        return "Calmer"
    return "Medium" if move_pct < BUMPIER_FROM_PCT else "Bumpier"


def analyze(holdings: list[Holding], closes: dict[str, list[int]] | None = None) -> PortfolioReport:
    """`closes` maps a symbol to its recent closing prices in cents, oldest first."""
    if not holdings:
        raise ValueError("a portfolio needs at least one holding")
    symbols = [h.symbol.upper() for h in holdings]
    if len(set(symbols)) != len(symbols):
        raise ValueError("each company should appear only once")

    closes = {k.upper(): v for k, v in (closes or {}).items()}
    total = sum(h.shares * h.price_cents for h in holdings)
    positions = sorted(
        (
            Position(
                symbol=h.symbol.upper(),
                shares=h.shares,
                value_cents=h.shares * h.price_cents,
                weight_pct=h.shares * h.price_cents / total * 100,
                daily_move_pct=daily_move_pct(closes.get(h.symbol.upper(), [])),
            )
            for h in holdings
        ),
        key=lambda p: p.value_cents,
        reverse=True,
    )
    largest = positions[0].weight_pct
    effective = 1 / sum((p.weight_pct / 100) ** 2 for p in positions)

    known = [p for p in positions if p.daily_move_pct is not None]
    known_weight = sum(p.weight_pct for p in known)
    move = sum(p.daily_move_pct * p.weight_pct for p in known) / known_weight if known else None
    return PortfolioReport(
        total_cents=total,
        positions=positions,
        largest_weight_pct=largest,
        effective_holdings=effective,
        spread=spread_for(largest, len(positions)),
        daily_move_pct=move,
        bumpiness=bumpiness_for(move),
    )
