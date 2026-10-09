"""What the app remembers about the player for one browser session.

Kept in `st.session_state`, so it lasts until the tab is closed. Saving it for good needs the
database (lane A).
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from pydantic import BaseModel, Field

from penny.contracts import GameFacts, GameState, Level
from penny.graph.types import KidContext

XP_PER_LEVEL = 100


class Player(BaseModel):
    started: bool = False
    nickname: str = ""
    level: Level = Level.STARTER
    coins: int = 0
    xp: int = 0
    streak: int = 0  # weeks in a row with something put in the jar
    goal_name: str = "Game"
    goal_cents: int = 6000
    saved_cents: int = 0  # everything put in the jar or earned at the stand this session

    # Games in progress. `*_last` holds the latest result while it is being shown.
    piggy: GameState | None = None
    piggy_last: GameFacts | None = None
    lemonade: GameState | None = None
    lemonade_last: GameFacts | None = None
    lemonade_profits: list[int] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.nickname.strip() or "friend"

    @property
    def xp_in_level(self) -> int:
        return self.xp % XP_PER_LEVEL

    @property
    def goal_progress(self) -> float:
        return min(1.0, max(0.0, self.saved_cents / self.goal_cents))

    def kid(self) -> KidContext:
        return KidContext(nickname=self.display_name, level=self.level)


def get_player(state: MutableMapping[str, Any]) -> Player:
    if "player" not in state:
        state["player"] = Player()
    return state["player"]


def reset_player(state: MutableMapping[str, Any]) -> Player:
    """Start over: a new player, and a fresh conversation with its own session id."""
    for key in (
        "chat",
        "session_id",
        "game",
        "piggy_save",
        "piggy_buy",
        "lemon_price",
        "lemon_cups",
    ):
        state.pop(key, None)
    state["player"] = Player()
    return state["player"]
