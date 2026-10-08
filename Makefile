.PHONY: setup test lint fmt run kb-check kb-links kb-index kb-index-dev kb-ask

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

# Real index: reviewed articles only, semantic model. Needs: uv sync --extra embeddings
kb-index:
	uv run python -m penny.kb.build

# Usage: make kb-ask Q="what is a stock?" EMB=hashing
kb-ask:
	uv run python -m penny.kb.ask "$(Q)" --embedder $(or $(EMB),minilm)
