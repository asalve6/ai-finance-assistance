"""The eval cases, loaded from data/evals/*.yaml. Each file is a list of cases for one suite."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from penny.contracts import Level
from penny.graph.types import SPECIALISTS

CASES_DIR = Path(__file__).resolve().parents[3] / "data" / "evals"


def _known_agent(agent: str | None) -> str | None:
    if agent is not None and agent not in SPECIALISTS:
        raise ValueError(f"unknown agent '{agent}', expected one of {SPECIALISTS}")
    return agent


class RoutingCase(BaseModel):
    id: str
    question: str
    agent: str
    history: list[str] = Field(default_factory=list)  # alternating child, Penny, child, ...
    mixed: bool = False

    _check_agent = field_validator("agent")(_known_agent)


class GuardianCase(BaseModel):
    id: str
    bad: bool  # True: the Guardian must reject this draft
    question: str
    evidence: str = ""
    draft: str
    level: Level = Level.STARTER


class RetrievalCase(BaseModel):
    id: str
    question: str
    article: str | None  # None: nothing should match well enough


class AnswerCase(BaseModel):
    id: str
    question: str
    level: Level = Level.STARTER
    before: list[str] = Field(default_factory=list)  # asked first, in the same session
    holdings: dict[str, int] = Field(default_factory=dict)
    route: str | None = None
    approved: bool = True
    contains: list[str] = Field(default_factory=list)
    not_contains: list[str] = Field(default_factory=list)
    also_ask: bool | None = None  # True: a second part must be offered. None: not checked

    _check_route = field_validator("route")(_known_agent)


def load[Case: BaseModel](kind: type[Case], name: str, directory: Path = CASES_DIR) -> list[Case]:
    cases = [kind.model_validate(item) for item in yaml.safe_load((directory / name).read_text())]
    ids = [c.id for c in cases]  # type: ignore[attr-defined]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise ValueError(f"{name}: repeated case ids {repeated}")
    return cases


def routing_cases(directory: Path = CASES_DIR) -> list[RoutingCase]:
    return load(RoutingCase, "routing.yaml", directory)


def guardian_cases(directory: Path = CASES_DIR) -> list[GuardianCase]:
    return load(GuardianCase, "guardian.yaml", directory)


def retrieval_cases(directory: Path = CASES_DIR) -> list[RetrievalCase]:
    return load(RetrievalCase, "retrieval.yaml", directory)


def answer_cases(directory: Path = CASES_DIR) -> list[AnswerCase]:
    return load(AnswerCase, "answers.yaml", directory)
