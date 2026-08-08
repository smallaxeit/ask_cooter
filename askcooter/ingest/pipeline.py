"""End-to-end ingestion, resumable and committed per page.

Each page is an independent unit of work: render -> extract -> chunk -> embed ->
store, committed on its own. Re-running skips pages already in the DB, so a run
interrupted at page 300 resumes cleanly. 651 vision calls will occasionally fail
(rate limits, transient errors); those pages are logged and left for a re-run.
"""
from __future__ import annotations

import json
import time

import anthropic
import voyageai

from ..config import cfg
from ..db import connect, existing_pdf_pages
from . import embed, render
from .chunk import chunk_markdown, token_count
from .extract import extract_page


# Substrings marking an error worth retrying: the output content-filter false
# positive (non-deterministic), model refusals, and transient server/rate errors.
_RETRY_MARKERS = (
    "content filter", "blocked", "refus", "overloaded",
    "rate limit", "timeout", "500", "529",
)


def _fallback_model() -> str:
    """The other tier, to retry pages the primary model won't extract."""
    return "claude-opus-5" if "opus" not in cfg.extract_model else "claude-sonnet-5"


def _extract_with_fallback(client, image_path):
    """Extract a page, retrying transient/filter errors and falling back to the
    other model. Raises the last error only if every attempt fails."""
    models = [cfg.extract_model]
    fb = _fallback_model()
    if fb != cfg.extract_model:
        models.append(fb)

    last_err = None
    for model in models:
        for attempt in range(2):
            try:
                ex = extract_page(image_path, client=client, model=model)
                if model != cfg.extract_model:
                    print(f"      (recovered via {model})")
                return ex
            except Exception as e:  # noqa: BLE001
                last_err = e
                if not any(m in str(e).lower() for m in _RETRY_MARKERS):
                    raise  # a real error (bad request shape, auth, etc.) — don't mask it
                time.sleep(1.5 * (attempt + 1))
    raise last_err


def _store_page(conn, pdf_page: int, image_path, ex, chunks, vectors) -> None:
    """Insert one page and its chunks in a single transaction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pages
                (pdf_page, printed_page, section, component_tags, image_path,
                 markdown, specs, diagrams)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            RETURNING id
            """,
            (
                pdf_page,
                ex.printed_page,
                ex.section,
                ex.component_tags,
                str(image_path),
                ex.markdown,
                json.dumps(ex.specs),
                json.dumps(ex.diagrams),
            ),
        )
        page_id = cur.fetchone()[0]

        for idx, (content, vec) in enumerate(zip(chunks, vectors)):
            cur.execute(
                """
                INSERT INTO chunks
                    (page_id, pdf_page, chunk_index, content, embedding, token_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (page_id, pdf_page, idx, content, vec, token_count(content)),
            )
    conn.commit()


def run(*, start: int = 0, end: int | None = None, overwrite: bool = False) -> None:
    """Ingest pages [start, end). ``end=None`` means through the last page."""
    cfg.require_ingest_keys()

    anthropic_client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    voyage_client = voyageai.Client(api_key=cfg.voyage_api_key)

    doc = render.open_pdf()
    total = doc.page_count
    end = total if end is None else min(end, total)

    with connect() as conn:
        done = set() if overwrite else existing_pdf_pages(conn)

        processed = failed = skipped = 0
        for pdf_page in range(start, end):
            if pdf_page in done and not overwrite:
                skipped += 1
                continue
            try:
                image_path = render.render_page(doc, pdf_page, overwrite=overwrite)
                ex = _extract_with_fallback(anthropic_client, image_path)
                chunks = chunk_markdown(ex.markdown)
                vectors = embed.embed_documents(chunks, client=voyage_client) if chunks else []

                if overwrite:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM pages WHERE pdf_page = %s", (pdf_page,))
                    conn.commit()

                _store_page(conn, pdf_page, image_path, ex, chunks, vectors)
                processed += 1
                print(
                    f"[{pdf_page + 1}/{total}] ok  "
                    f"printed={ex.printed_page!r:>8}  chunks={len(chunks)}  "
                    f"specs={len(ex.specs)}  diagrams={len(ex.diagrams)}"
                )
            except Exception as e:  # noqa: BLE001 — keep going; one bad page shouldn't stop the run
                failed += 1
                conn.rollback()
                print(f"[{pdf_page + 1}/{total}] FAILED: {type(e).__name__}: {e}")
                time.sleep(1.0)  # brief backoff on transient errors

    doc.close()
    print(
        f"\nDone. processed={processed} skipped={skipped} failed={failed}. "
        f"Re-run the same command to retry failed pages."
    )
