"""Postgres/pgvector connection helpers.

A thin wrapper over psycopg 3. ``connect()`` registers the pgvector adapter so
embeddings can be passed as plain Python lists.
"""
from __future__ import annotations

from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from .config import cfg

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect() -> psycopg.Connection:
    """Open a connection with the pgvector type adapter registered."""
    conn = psycopg.connect(cfg.database_url)
    register_vector(conn)
    return conn


def init_db() -> None:
    """Create the extension, tables, and indexes (idempotent)."""
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(ddl)
        conn.commit()


def existing_pdf_pages(conn: psycopg.Connection) -> set[int]:
    """PDF page numbers already ingested — used to make the pipeline resumable."""
    with conn.cursor() as cur:
        cur.execute("SELECT pdf_page FROM pages")
        return {row[0] for row in cur.fetchall()}
