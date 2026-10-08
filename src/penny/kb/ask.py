"""Try a search: `python -m penny.kb.ask "what is a stock?" [--level starter]`."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from penny.config import load_env
from penny.contracts import Level
from penny.kb.embedding import DEFAULT_EMBEDDER, get_embedder
from penny.kb.index import INDEX_DIR, KBIndex
from penny.kb.retriever import retrieve


def main(argv: list[str] | None = None) -> int:
    load_env()  # first, so KB_EMBEDDER from .env is seen by the argument defaults
    parser = argparse.ArgumentParser(prog="python -m penny.kb.ask")
    parser.add_argument("query")
    parser.add_argument("--index", type=Path, default=INDEX_DIR)
    parser.add_argument("--embedder", default=os.getenv("KB_EMBEDDER", DEFAULT_EMBEDDER))
    parser.add_argument("--level", choices=[level.value for level in Level], default=None)
    parser.add_argument("-k", type=int, default=4)
    args = parser.parse_args(argv)

    level = Level(args.level) if args.level else None
    try:
        index = KBIndex.load(get_embedder(args.embedder), args.index)
        result = retrieve(index, args.query, k=args.k, max_level=level)
    except FileNotFoundError:
        print(f"No index found at {args.index}. Build one first: make kb-index")
        return 2
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 2

    if not result.confident:
        print(f"Not confident ({result.reason}). Penny would say it does not know.")
        return 0
    for hit in result.hits:
        print(f"{hit.score:.2f}  {hit.chunk.article_id} / {hit.chunk.heading}")
        print(f"      {hit.chunk.text[:110]}")
    print("\nSources")
    for citation in result.citations():
        print(f"  {citation.title}")
        for source in citation.sources:
            print(f"    {source.title}: {source.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
