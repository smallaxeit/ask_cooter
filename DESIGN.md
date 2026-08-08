# Ask Cooter — Design Doc

> Turn any PDF — including scanned, text-free ones — into a private, cited
> knowledge expert (CLI + local chat UI + MCP server).
> **Initial corpus:** a Harley-Davidson Softail (1984–1999) scanned service manual.
> Status: **built and running locally** (single-corpus MVP).

---

## 1. Decisions (as built)

| Area | Decision |
|---|---|
| Scope | Any PDF via `PDF_PATH`; Softail manual is the initial corpus. One PDF per database. |
| Audience | **Private / personal.** Public multi-user path noted but not the default — see §6 copyright. |
| Language | **Python 3.13** (pipeline, MCP server, web UI) |
| Page extraction | **Claude vision** (`EXTRACT_MODEL`, default `claude-opus-5`; `claude-sonnet-5` for cheap bulk runs) — structured JSON: text + tables + figure descriptions + specs |
| Embeddings | **Voyage** `voyage-3.5`, 1024-dim (Anthropic has no embeddings API) |
| Vector store | **PostgreSQL 18 + pgvector 0.8.6**, native Windows, **no Docker**; HNSW cosine index |
| Answer layer | Retrieval + **Claude synthesis** (`ANSWER_MODEL`, default `claude-opus-5`), cited |
| Serving | MCP over **stdio** (FastMCP), a **CLI**, and a local **FastAPI chat UI** |
| Citations | **Mandatory** — every answer cites source page(s) so the user can open the PDF |
| User history | Table exists, **unused in MVP** (forward-compatible; no auth) |

## 2. The core problem (why this isn't just "chunk a PDF")

The initial source, `Softail-1984-1999-Repair-Manual-Harley-Davidson.pdf`, is
**651 pages, 191 MB, scanned images with ~0 extractable text** (verified: sampled
pages return 0 chars; page 1 only has a watermark). Everything valuable is *pixels*:
torque-spec tables, exploded parts diagrams, wiring schematics, and step-by-step
procedures with figure callouts.

Plain OCR (Tesseract) reads body text okay but mangles tables and ignores diagrams
— i.e. it fails exactly where a repair manual's value lives. Hence the core
decision: **use a Claude vision model to extract each page** into clean markdown +
reconstructed tables + text descriptions of every figure. Final answer quality is
bounded by ingestion quality, so the investment goes there — not the vector layer.
(This generalizes: the same pipeline handles any scanned or digital PDF.)

## 3. Architecture

### 3.1 Ingestion pipeline (one-time, offline, resumable)

```
PDF (PDF_PATH)
  → render each page to PNG at 150 DPI                     (PyMuPDF)
  → Claude vision extraction per page → structured JSON:
        - printed_page (the label on the page, e.g. "3-14")
        - section (running header)
        - component_tags[]
        - markdown (body text + tables reconstructed as markdown + figure text)
        - specs[]    ({name, value, unit, notes})
        - diagrams[] ({figure, title, description})
  → chunk the markdown (structure-aware, char-based; ~1400 target / 2200 max)
  → Voyage embedding per chunk (input_type=document)
  → store pages + chunks (+ page image path) → Postgres/pgvector
```

Resilience:
- **Per-page commit + skip** makes the run resumable — re-run to continue.
- **Retry + model fallback:** transient errors, model refusals, and the Anthropic
  *output content-filter* false positives are retried, then retried on the other
  model tier (opus↔sonnet). Pages that still fail are logged for a later re-run.
- The rendered page image is kept on disk (`image_path`) so answers can reference
  the original scan.

### 3.2 Retrieval (per query)

```
question
  → Voyage embed (input_type=query)
  → pgvector cosine search (HNSW), optional component-tag filter
  → top-K chunks joined to their pages → content + citations (+ image path)
```

### 3.3 Answer synthesis (the `ask` layer)

`answer.py` retrieves the top-K passages, formats them with their citations, and
asks Claude (`ANSWER_MODEL`) to write a direct answer that:
- leads with the specific answer,
- cites source pages inline as `[PDF p.N]`,
- preserves exact specs/torque/step order verbatim,
- says so (and points to where it likely lives) when the excerpts don't contain it.

### 3.4 Serving surfaces

- **CLI** (`askcooter.cli`): `init-db`, `ingest`, `ask`, `query`, `sections`,
  `web`, `serve`.
- **MCP server** (stdio, FastMCP) — 5 tools:
  - `ask(question, limit)` → direct cited answer (retrieval + synthesis)
  - `search_manual(query, limit, component)` → ranked passages + citations
  - `get_page(pdf_page)` → full page text + specs + figures + image path
  - `get_torque_spec(component)` → structured spec lookup
  - `list_sections()` → section table of contents
- **Chat UI** (`askcooter/web`): FastAPI + streaming SSE, single self-contained
  page. Renders markdown, keeps multi-turn context, and turns source citations
  into links that open the original page (extracted text + the scanned image via
  `/api/page` and `/api/page-image`).

### 3.5 Citations & page traceability (hard requirement)

- Store **both** numbers per page: `pdf_page` (position in the file — 0-based
  internally, shown 1-based) and `printed_page` (the manual's own label, nullable).
  They differ because of front matter (validated: PDF page 540 == printed 541).
- Answers cite pages so the user can open the PDF to the original scan.

## 4. Data model (as built — see `askcooter/schema.sql`)

```sql
pages(
  id, pdf_page int UNIQUE,        -- position in the PDF (0-based); primary jump key
  printed_page text,              -- manual's own label, e.g. '3-14' (nullable)
  section text,
  component_tags text[],
  image_path text,               -- rendered PNG on disk
  markdown text,                 -- clean extracted text (chunk source)
  specs jsonb,                   -- [{name,value,unit,notes}]
  diagrams jsonb,                -- [{figure,title,description}]
  created_at timestamptz
)

chunks(
  id, page_id fk, pdf_page int, chunk_index int,
  content text, embedding vector(1024),   -- dim must match EMBED_DIM / Voyage model
  token_count int, created_at timestamptz
)
-- HNSW cosine index on embedding.

-- FUTURE (unused in MVP): no auth → opaque client token.
user_history(
  id, user_token text, question text, answer text,
  cited_pdf_pages int[], bike_profile jsonb, created_at timestamptz
)
```

## 5. Cost notes

- **Ingestion dominates and is Claude, not Voyage.** One vision call per page.
  Full Softail run ≈ **$12–18 on `claude-sonnet-5`** (≈ $30–45 on opus). One-time.
- **Voyage embeddings:** ~250–300K tokens for the whole manual → **a couple of
  cents** (likely free under Voyage's free tier).
- **Per query:** 1 Voyage embed (trivial) + (for `ask`) 1 Claude synthesis call.

## 6. Open items / risks

1. **Copyright** — the source PDF may be copyrighted (the Softail manual is). Private
   use is the intended mode; the PDF and rendered images are gitignored. Reconsider
   before any public/redistributing deployment.
2. **Single corpus per DB** — results rank across everything in the DB; switch PDFs
   via a fresh `DATABASE_URL` (or truncate `pages`/`chunks`).
3. **Extraction quality on the densest diagrams** — Sonnet is the default bulk
   model; spot-check figure-heavy pages and re-extract those on opus if needed.
4. **Embedding dimension is hardcoded** (`VECTOR(1024)`); changing the Voyage model
   requires a DDL change and a full re-embed (no migration path).
5. **No answer-level verification** — citations are prompt-enforced, not checked.
7. **Follow-up retrieval** — the chat UI passes prior turns to the answer model,
   but retrieval embeds only the current question. Pronoun/elliptical follow-ups
   ("what about the front one?") may retrieve poorly; query rewriting would fix it.
6. **Windows/EDB-specific build** — pgvector was compiled from source for PG18
   (ships no Windows binaries); see README. Not portable as-is.

## 6a. Prototype results (validated during design)

Vision extraction was validated on 10 spread-out pages before the full build:
rendering is clean despite zero embedded text; worst-case wiring/test diagrams
(page 540 / printed 541) extracted correctly (figure numbers, wire colors, specs
"1 ohm or less" / "12 volts"); the pdf_page↔printed_page offset was confirmed.
Sample: `prototype/sample_extraction_page540.json`.

## 7. Build status

Done: schema + pgvector (PG18), resumable ingestion with retry/fallback, retrieval,
answer synthesis, MCP server (5 tools), CLI, and chat UI. Prototype ingest verified
end-to-end; full ingest is a user-run step.

Not built (deliberately, for private MVP): auth, remote/HTTP transport, multi-tenant
hosting, and the `user_history` feature.
