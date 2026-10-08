.PHONY: setup test lint fmt run kb-check kb-links kb-index kb-index-dev kb-ask llm-smoke

setup:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check .

fmt:
	uv run ruff check --fix . && uv run ruff format .

run:
	uv run streamlit run src/penny/ui/app.py

kb-check:
	uv run python -m penny.kb

kb-links:
	uv run python -m penny.kb --links

# Offline development index (word matching, includes unreviewed articles). No downloads.
kb-index-dev:
	uv run python -m penny.kb.build --embedder hashing --include-drafts

# Real index: reviewed articles only, OpenAI embeddings (needs OPENAI_API_KEY in .env)
kb-index:
	uv run python -m penny.kb.build

# Usage: make kb-ask Q="what is a stock?"   (add EMB=hashing for the offline test index)
kb-ask:
	uv run python -m penny.kb.ask "$(Q)" $(if $(EMB),--embedder $(EMB),)

# Live check of the configured LLM provider (a few hundred tokens). Needs a key in .env.
llm-smoke:
	uv run python -m penny.llm.smoke
