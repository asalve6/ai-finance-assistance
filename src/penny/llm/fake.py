"""Scripted LLM for tests and offline UI work. Lets every lane run without an API key."""

from __future__ import annotations

from typing import Any

from penny.contracts import Effort, LLMResponse, Message, ToolSpec


class FakeLLM:
    """Returns pre-scripted responses in order and records every call it receives."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int | None = None,
        effort: Effort | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "system": system,
                "messages": list(messages),
                "tools": tools,
                "max_tokens": max_tokens,
                "effort": effort,
            }
        )
        if not self._script:
            raise AssertionError("FakeLLM script exhausted: more LLM calls than expected")
        return self._script.pop(0)
