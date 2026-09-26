"""Retrieval layer: embed a query, search pgvector, return cited results.

Every result carries both page numbers (pdf_page for jumping, printed_page for
cross-reference) plus the image path, so the caller can always point the user
back to the original scan (DESIGN.md §3.5).
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import cfg
from .db import connect
from .ingest.embed import embed_query


@dataclass
class SearchResult:
    pdf_page: int
    printed_page: str | None
    section: str | None
    content: str
    image_path: str | None
    score: float  # cosine similarity in [0, 1]; higher is closer

    def citation(self) -> str:
        printed = f" (printed {self.printed_page})" if self.printed_page else ""
        sect = f' — "{self.section}"' if self.section else ""
        return f"PDF p.{self.pdf_page + 1}{printed}{sect}"


def search_manual(query: str, *, limit: int | None = None, component: str | None = None) -> list[SearchResult]:
    """Vector search over chunks. Optional ``component`` filters by page tag."""
    limit = limit or cfg.search_limit
    qvec = embed_query(query)

    # Cast the query param to `vector` explicitly: psycopg sends a Python list as
    # double precision[], and (unlike INSERT's assignment context) the <=> operator
    # has no implicit cast from an array.
    sql = """
        SELECT c.pdf_page, p.printed_page, p.section, c.content, p.image_path,
               1 - (c.embedding <=> %(qvec)s::vector) AS score
        FROM chunks c
        JOIN pages p ON p.id = c.page_id
        {where}
        ORDER BY c.embedding <=> %(qvec)s::vector
        LIMIT %(limit)s
    """
    params: dict = {"qvec": qvec, "limit": limit}
    where = ""
    if component:
        where = "WHERE %(component)s = ANY (p.component_tags)"
        params["component"] = component.lower()
    sql = sql.format(where=where)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        SearchResult(
            pdf_page=r[0],
            printed_page=r[1],
            section=r[2],
            content=r[3],
            image_path=r[4],
            score=float(r[5]),
        )
        for r in rows
    ]


@dataclass
class Page:
    pdf_page: int
    printed_page: str | None
    section: str | None
    markdown: str
    specs: list
    diagrams: list
    image_path: str | None


def get_page(pdf_page: int) -> Page | None:
    """Fetch a full page by its 0-based PDF position."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pdf_page, printed_page, section, markdown, specs, diagrams, image_path
            FROM pages WHERE pdf_page = %s
            """,
            (pdf_page,),
        )
        r = cur.fetchone()
    if not r:
        return None
    return Page(
        pdf_page=r[0], printed_page=r[1], section=r[2], markdown=r[3],
        specs=r[4], diagrams=r[5], image_path=r[6],
    )


def find_specs(query: str, *, limit: int = 25) -> list[dict]:
    """Full-text-ish lookup over the structured `specs` on every page.

    Matches the query against spec name/notes and the page's component tags.
    Returns spec dicts enriched with page citation fields.
    """
    # Escape LIKE metacharacters so a query containing % or _ matches literally
    # rather than turning into a wildcard.
    escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    sql = """
        SELECT p.pdf_page, p.printed_page, p.section, s.spec
        FROM pages p
        CROSS JOIN LATERAL jsonb_array_elements(p.specs) AS s(spec)
        WHERE lower(s.spec->>'name') LIKE %(like)s
           OR lower(coalesce(s.spec->>'notes', '')) LIKE %(like)s
           OR EXISTS (
                SELECT 1 FROM unnest(p.component_tags) t
                WHERE t LIKE %(like)s
           )
        LIMIT %(limit)s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, {"like": like, "limit": limit})
        rows = cur.fetchall()

    out = []
    for pdf_page, printed_page, section, spec in rows:
        out.append(
            {
                "pdf_page": pdf_page,
                "printed_page": printed_page,
                "section": section,
                **spec,
            }
        )
    return out


def list_sections() -> list[dict]:
    """Distinct sections with their PDF page ranges (a lightweight TOC)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT section, min(pdf_page) AS first_page, max(pdf_page) AS last_page,
                   count(*) AS pages
            FROM pages
            WHERE section IS NOT NULL AND section <> ''
            GROUP BY section
            ORDER BY first_page
            """
        )
        rows = cur.fetchall()
    return [
        {"section": r[0], "first_pdf_page": r[1], "last_pdf_page": r[2], "pages": r[3]}
        for r in rows
    ]
