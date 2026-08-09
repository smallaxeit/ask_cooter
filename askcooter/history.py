"""Persistent question/answer history in the ``user_history`` table.

No auth: rows are keyed by an opaque, client-generated ``user_token`` (a random
id the browser stores in localStorage). Storing full answers turns history into a
reusable log — a past question can be reopened with its saved answer instead of
paying to regenerate it.
"""
from __future__ import annotations

import json

from .db import connect


def record(
    user_token: str | None,
    question: str,
    answer: str,
    cited_pdf_pages: list[int],
    bike: str | None,
) -> None:
    """Insert one completed Q&A. No-op without a token or answer."""
    if not user_token or not answer:
        return
    profile = json.dumps({"bike": bike}) if bike else None
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_history
                (user_token, question, answer, cited_pdf_pages, bike_profile)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (user_token, question, answer, cited_pdf_pages, profile),
        )
        conn.commit()


def list_for(user_token: str, limit: int = 100) -> list[dict]:
    """Most-recent-first history for a token, with the saved answers."""
    if not user_token:
        return []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, question, answer, cited_pdf_pages, bike_profile, created_at
            FROM user_history
            WHERE user_token = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (user_token, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "question": r[1],
            "answer": r[2],
            "cited_pdf_pages": r[3] or [],
            "bike": (r[4] or {}).get("bike") if r[4] else None,
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


def clear(user_token: str) -> int:
    """Delete all history for a token. Returns rows removed."""
    if not user_token:
        return 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM user_history WHERE user_token = %s", (user_token,))
        n = cur.rowcount
        conn.commit()
    return n
