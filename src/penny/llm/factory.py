"""Pick the LLM provider and models from the environment.

    LLM_PROVIDER    anthropic (default) | openai
    LLM_MODEL_FAST  the cheap, quick model (routing, review). Optional.
    LLM_MODEL_MAIN  the answering model. Optional.

Unset models fall back to a default for the chosen provider. A model name that clearly belongs to
the other provider is refused up front, because the usual mistake is switching LLM_PROVIDER and
leaving the old model names in .env.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from penny.contracts import LLMClient
from penny.llm.anthropic_client import AnthropicClient
from penny.llm.errors import LLMError
from penny.llm.openai_client import OpenAIClient

DEFAULT_MODELS = {
    "anthropic": {"fast": "claude-haiku-5-5", "main": "claude-sonnet-5-5"},
    "openai": {"fast": "gpt-4o-mini", "main": "gpt-4o"},
}


@dataclass(frozen=True)
class LLMSetup:
    client: LLMClient
    provider: str
    fast_model: str
    main_model: str


def _check_model(provider: str, variable: str, model: str) -> None:
    is_claude = model.lower().startswith("claude")
    if (provider == "openai") == is_claude:  # a Claude name under OpenAI, or the reverse
        looks_like = "an Anthropic (Claude)" if is_claude else "a non-Claude"
        needs = "an OpenAI" if provider == "openai" else "a Claude"
        default = DEFAULT_MODELS[provider][variable.split("_")[-1].lower()]
        raise LLMError(
            f"{variable}='{model}' looks like {looks_like} model, but LLM_PROVIDER={provider}. "
            f"Set {variable} to {needs} model, or remove the line to use '{default}'."
        )


def get_llm(provider: str | None = None, env: Mapping[str, str] | None = None) -> LLMSetup:
    env = os.environ if env is None else env
    provider = (provider or env.get("LLM_PROVIDER") or "anthropic").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise LLMError(f"Unknown LLM_PROVIDER '{provider}'. Use 'anthropic' or 'openai'.")

    models = {}
    for tier in ("fast", "main"):
        variable = f"LLM_MODEL_{tier.upper()}"
        configured = (env.get(variable) or "").strip()
        if configured:
            _check_model(provider, variable, configured)
        models[tier] = configured or DEFAULT_MODELS[provider][tier]

    client: LLMClient = AnthropicClient() if provider == "anthropic" else OpenAIClient()
    return LLMSetup(
        client=client, provider=provider, fast_model=models["fast"], main_model=models["main"]
    )
