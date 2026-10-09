"""The first-run quiz. It is scored here in code, never by a model."""

from __future__ import annotations

from dataclasses import dataclass

from penny.contracts import Level


@dataclass(frozen=True)
class Question:
    text: str
    options: tuple[str, ...]
    answer: int  # index of the right option


QUESTIONS: tuple[Question, ...] = (
    Question(
        "You get $10 allowance and want a $40 game. What helps most?",
        ("Spend it all today", "Save a little each week", "Wait and hope for a gift"),
        1,
    ),
    Question(
        "What is interest?",
        (
            "A fee for opening a piggy bank",
            "Extra money a bank pays you for saving",
            "A discount coupon",
        ),
        1,
    ),
    Question(
        "A cup costs $0.20 to make and sells for $0.75. The $0.55 left over is called...",
        ("Profit", "Tax", "Allowance"),
        0,
    ),
)


def score(answers: list[int | None]) -> int:
    return sum(1 for q, a in zip(QUESTIONS, answers, strict=True) if a == q.answer)


def level_for(answers: list[int | None]) -> Level:
    """All three right is a Builder, two is a Saver, anything less (or skipped) is a Starter."""
    correct = score(answers)
    if correct >= 3:
        return Level.BUILDER
    return Level.SAVER if correct == 2 else Level.STARTER
