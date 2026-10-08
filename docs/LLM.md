# LLM providers

Agents talk to a provider-neutral `LLMClient` (see `src/penny/contracts.py`). Two adapters implement it,
and `get_llm()` picks one from the environment.

| Setting in `.env` | Meaning |
|---|---|
| `LLM_PROVIDER` | `anthropic` (default) or `openai` |
| `LLM_MODEL_FAST` | Cheap, quick model for routing and review. Blank = provider default |
| `LLM_MODEL_MAIN` | Model that writes answers. Blank = provider default |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Only the key for the chosen provider is needed |

Defaults: Anthropic `claude-haiku-5-5` / `claude-sonnet-5-5`. OpenAI `gpt-4o-mini` / `gpt-4o`.

## Check it works

```bash
make llm-smoke                        # uses .env
uv run python -m penny.llm.smoke --provider openai --tier main
```

It asks a question that needs a tool, runs the tool, sends the result back, and checks the answer.
That exercises the whole tool-call round trip against the real API for a few hundred tokens.

## What the adapters hide

| | Anthropic | OpenAI |
|---|---|---|
| System prompt | separate `system` field | first message |
| Tool results | one user message of `tool_result` blocks | one `tool` message per result |
| Tool arguments | already a dict | a JSON string, parsed. A bad string sets `ToolCall.error` |
| Thinking blocks | replayed unchanged from `provider_state` | not used |
| `effort` | `output_config.effort` | `reasoning_effort`, only for o-series and gpt-5 |
| Stop reasons | `end_turn`, `tool_use`, `max_tokens`, `refusal`, else `other` | same, mapped from `finish_reason` |

All provider failures are raised as `LLMError` with a `retryable` flag, so agents never import an SDK's
exceptions. Rate limits, timeouts, network errors and 5xx are retryable. Bad requests and bad keys are not.

`max_tokens` includes any thinking tokens, so do not set it too low (the default is 4096).

## Status

OpenAI: verified against the live API (tool round trip on `gpt-4o-mini` and `gpt-4o`, and `reasoning_effort` on `gpt-5`).
Anthropic: covered by tests against a fake client only. Run `make llm-smoke` with a key to verify it.
