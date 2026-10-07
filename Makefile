.PHONY: setup test lint fmt run

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
