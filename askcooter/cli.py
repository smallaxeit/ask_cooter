"""Command-line entry points.

    python -m askcooter.cli init-db
    python -m askcooter.cli ingest [--start N] [--end N] [--overwrite]
    python -m askcooter.cli query "how much oil does the primary hold?"
    python -m askcooter.cli sections
    python -m askcooter.cli serve            # run the MCP server (stdio)
"""
from __future__ import annotations

import argparse
import sys


def _cmd_init_db(_args) -> int:
    from .db import init_db

    init_db()
    print("Schema created.")
    return 0


def _cmd_ingest(args) -> int:
    from .ingest.pipeline import run

    run(start=args.start, end=args.end, overwrite=args.overwrite)
    return 0


def _cmd_query(args) -> int:
    from .retrieval import search_manual

    results = search_manual(args.text, limit=args.limit)
    if not results:
        print("No matches.")
        return 0
    for i, r in enumerate(results, 1):
        print(f"\n=== Result {i} — {r.citation()}  (similarity {r.score:.2f}) ===")
        print(r.content.strip())
    return 0


def _cmd_ask(args) -> int:
    from .answer import answer

    res = answer(args.text, limit=args.limit)
    print(res.answer)
    if res.sources:
        print("\nSources:")
        for s in res.sources:
            print(f"  - {s.citation()}")
    return 0


def _cmd_web(args) -> int:
    import uvicorn

    print(f"Ask Cooter chat UI -> http://{args.host}:{args.port}")
    uvicorn.run("askcooter.web.app:app", host=args.host, port=args.port, reload=False)
    return 0


def _cmd_sections(_args) -> int:
    from .retrieval import list_sections

    for s in list_sections():
        print(
            f"PDF p.{s['first_pdf_page'] + 1}-{s['last_pdf_page'] + 1}: "
            f"{s['section']} ({s['pages']} pages)"
        )
    return 0


def _cmd_serve(_args) -> int:
    from .mcp_server import main

    main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="askcooter", description="Ask Cooter CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the pgvector schema").set_defaults(func=_cmd_init_db)

    ing = sub.add_parser("ingest", help="render, extract, embed, and store pages")
    ing.add_argument("--start", type=int, default=0, help="first PDF page (0-based, inclusive)")
    ing.add_argument("--end", type=int, default=None, help="last PDF page (exclusive)")
    ing.add_argument("--overwrite", action="store_true", help="re-ingest pages already in the DB")
    ing.set_defaults(func=_cmd_ingest)

    q = sub.add_parser("query", help="vector-search the manual from the terminal")
    q.add_argument("text", help="the question / search text")
    q.add_argument("--limit", type=int, default=5)
    q.set_defaults(func=_cmd_query)

    a = sub.add_parser("ask", help="get a direct, cited answer (retrieval + Claude)")
    a.add_argument("text", help="the question")
    a.add_argument("--limit", type=int, default=6, help="passages to retrieve for context")
    a.set_defaults(func=_cmd_ask)

    w = sub.add_parser("web", help="launch the local chat UI")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)
    w.set_defaults(func=_cmd_web)

    sub.add_parser("sections", help="print the section table of contents").set_defaults(
        func=_cmd_sections
    )

    sub.add_parser("serve", help="run the MCP server over stdio").set_defaults(func=_cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
