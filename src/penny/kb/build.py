"""Build the search index: `python -m penny.kb.build [--include-drafts] [--embedder hashing]`."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from penny.kb.article import KB_DIR, load_articles
from penny.kb.embedding import get_embedder
from penny.kb.index import INDEX_DIR, KBIndex


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m penny.kb.build")
    parser.add_argument("--dir", type=Path, default=KB_DIR, help="knowledge-base folder")
    parser.add_argument("--out", type=Path, default=INDEX_DIR, help="where to save the index")
    parser.add_argument("--embedder", default=os.getenv("KB_EMBEDDER", "minilm"))
    parser.add_argument(
        "--include-drafts", action="store_true", help="also index articles not yet reviewed"
    )
    args = parser.parse_args(argv)

    articles = [article for _, article in load_articles(args.dir / "articles")[0]]
    if not articles:
        print("No articles found.")
        return 1
    reviewed = sum(a.reviewed for a in articles)
    index = KBIndex.build(articles, get_embedder(args.embedder), include_drafts=args.include_drafts)
    index.save(args.out)

    indexed = len(articles) if args.include_drafts else reviewed
    print(f"Indexed {indexed} of {len(articles)} articles ({index.meta.chunk_count} chunks)")
    print(f"Embedder: {index.meta.embedder}. Saved to {args.out}")
    if indexed < len(articles):
        print(
            f"{len(articles) - indexed} unreviewed article(s) left out. Use --include-drafts "
            "for development only."
        )
    if reviewed == 0 and not args.include_drafts:
        print(
            "No article is reviewed yet, so the index is empty. Set 'reviewed: true' on "
            "articles you have checked."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
