# Ask Cooter — Design Doc

Ask Cooter turns a PDF into a searchable, cited knowledge base, including scanned
PDFs with no extractable text. It ships three interfaces over one corpus: a CLI, a
local chat UI, and an MCP server.

Initial corpus: a Harley-Davidson Softail (1984–1999) scanned service manual.
Status: built and running locally, single corpus, private use.

---

## 1. Decisions as built

| Area | Decision |
|---|---|
| Scope | Any PDF via `PDF_PATH`. One PDF per database. |
| Audience | Private / personal. No auth. A public multi-user path is possible but not the default; see §7 on copyright. |
| Language | Python 3.13 (pipeline, MCP server, web UI) |
| Page extraction | Claude vision (`EXTRACT_MODEL`, default `claude-opus-5`; `claude-sonnet-5` for cheaper bulk runs) returning structured JSON |
| Embeddings | Voyage `voyage-3.5`, 1024-dim. Anthropic has no embeddings API. |
| Vector store | PostgreSQL 18 + pgvector 0.8.6, native Windows, no Docker. HNSW cosine index. |
| Answer layer | Retrieval plus Claude synthesis (`ANSWER_MODEL`, default `claude-opus-5`) |
| Serving | MCP over stdio (FastMCP), a CLI, and a local FastAPI chat UI |
| Citations | Required. Every answer cites the source page(s) so the reader can open the PDF. |
| User history | `user_history` table, written and read by the chat UI, keyed by an opaque client token |

## 2. Why chunking the PDF is not enough

The initial source, `Softail-1984-1999-Repair-Manual-Harley-Davidson.pdf`, is 651
pages and 191 MB of scanned images with essentially no extractable text. Sampled
pages return 0 characters; page 1 returns only a watermark. The content that
matters is all pixels: torque-spec tables, exploded parts diagrams, wiring
schematics, and procedures that refer to figure callouts.

Tesseract reads body text acceptably but mangles table structure and skips
diagrams entirely, which is most of a repair manual's content. So each page goes
through a Claude vision model instead, producing markdown, reconstructed tables,
and text descriptions of each figure. Answer quality is capped by extraction
quality, so that is where the cost and complexity sit rather than in the vector
layer. The same pipeline works on digital PDFs without changes.

## 3. Architecture

### 3.1 Ingestion (one-time, offline, resumable)

```
PDF (PDF_PATH)
  → render each page to PNG at 150 DPI                     (PyMuPDF)
  → Claude vision extraction per page → structured JSON:
        - printed_page (the label printed on the page, e.g. "3-14")
        - section (running header)
        - component_tags[]
        - markdown (body text, tables as markdown, figure text)
        - specs[]    ({name, value, unit, notes})
        - diagrams[] ({figure, title, description})
  → chunk the markdown (structure-aware, char-based; 1400 target / 2200 max)
  → Voyage embedding per chunk (input_type=document)
  → store pages + chunks + page image path → Postgres/pgvector
```

Failure handling:

- Each page is committed on its own and already-stored pages are skipped, so a
  run resumes by re-running it.
- Transient errors, model refusals, and false positives from the Anthropic output
  content filter are retried, then retried on the other model tier
  (opus ↔ sonnet). Pages that still fail are logged for a later run.
- The rendered PNG stays on disk (`image_path`) so answers can point at the
  original scan.

### 3.2 Retrieval (per query)

```
question
  → Voyage embed (input_type=query)
  → pgvector cosine search (HNSW), optional component-tag filter
  → top-K chunks joined to their pages → content + citations + image path
```

### 3.3 Answer synthesis

`answer.py` retrieves the top-K passages, formats them with their citations, and
asks `ANSWER_MODEL` for an answer that:

- leads with the specific answer,
- cites source pages inline as `[PDF p.N]`,
- reproduces specs, torque values, and step order verbatim,
- states when the excerpts do not contain the answer, and where it likely lives.

### 3.4 Interfaces

CLI (`askcooter.cli`): `init-db`, `ingest`, `ask`, `query`, `sections`, `web`,
`serve`.

MCP server (stdio, FastMCP), five tools:

- `ask(question, limit)` — cited answer (retrieval + synthesis)
- `search_manual(query, limit, component)` — ranked passages + citations
- `get_page(pdf_page)` — page text, specs, figures, image path
- `get_torque_spec(component)` — structured spec lookup
- `list_sections()` — section table of contents

Chat UI (`askcooter/web`): FastAPI with SSE streaming and a single self-contained
page. It renders markdown, keeps multi-turn context, and turns citations into
links that open the original page — extracted text plus the scanned image, via
`/api/page` and `/api/page-image`, with zoom and page-flip driven by `/api/meta`.
A bike profile (year/model) is sent with each question and injected into the
synthesis prompt. Each Q&A is written to `user_history` through `/api/history`;
the sidebar reads from the database, and clicking a past question replays the
saved answer and sources without an API call.

### 3.5 Citations and page traceability

Each page stores two numbers: `pdf_page`, its position in the file (0-based
internally, displayed 1-based), and `printed_page`, the label printed on the page
itself (nullable). They diverge because of front matter — PDF page 540 is printed
page 541 in this manual. Answers cite pages so the reader can open the PDF at the
original scan.

## 4. Data model

See `askcooter/schema.sql`.

```sql
pages(
  id, pdf_page int UNIQUE,       -- position in the PDF (0-based); primary jump key
  printed_page text,             -- label printed on the page, e.g. '3-14' (nullable)
  section text,
  component_tags text[],
  image_path text,               -- rendered PNG on disk
  markdown text,                 -- extracted text; the chunk source
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

-- Written and read by the chat UI. No auth, so rows are keyed by an opaque
-- client token. Read and deleted via /api/history.
user_history(
  id, user_token text, question text, answer text,
  cited_pdf_pages int[], bike_profile jsonb, created_at timestamptz
)
```

## 5. Costs

Ingestion dominates, and it is Claude rather than Voyage: one vision call per
page. A full Softail run is roughly $12–18 on `claude-sonnet-5` or $30–45 on
opus, once.

Voyage embeddings come to 250–300K tokens for the whole manual, a few cents, and
likely nothing under the free tier.

Per query: one Voyage embed, plus one Claude synthesis call for `ask`.

## 6. Prototype validation

Vision extraction was checked on 10 spread-out pages before the full build.
Rendering was clean despite the absence of embedded text. The worst case tried —
a wiring/test diagram on PDF page 540, printed page 541 — extracted correctly,
including figure numbers, wire colors, and the specs "1 ohm or less" and "12
volts". That page also confirmed the `pdf_page` / `printed_page` offset. Sample
output: `prototype/sample_extraction_page540.json`.

## 7. Open items and risks

1. Copyright. The source PDF is copyrighted. Ask Cooter is built for personal use
   on a manual you own: the PDF and the rendered images stay gitignored, and the
   extracted text in Postgres is a copy of the manual, so it stays local too. One
   extracted page is committed under `prototype/` as a schema reference. Hosting
   this where others can query it means redistributing the manual's content, which
   is a different question — settle it before deploying.
2. One corpus per database. Results rank across everything in the database;
   switching PDFs means a fresh `DATABASE_URL`, or truncating `pages` and
   `chunks`.
3. Extraction quality on the densest diagrams. Sonnet is the cheap bulk option;
   spot-check figure-heavy pages and re-extract those on opus if needed.
4. Embedding dimension is hardcoded as `VECTOR(1024)`. Changing the Voyage model
   requires a DDL change and a full re-embed. There is no migration path.
5. No answer-level verification. Citations are enforced by prompt, not checked
   against the retrieved passages.
6. Follow-up retrieval. The chat UI passes prior turns to the answer model, but
   retrieval embeds only the current question, so elliptical follow-ups ("what
   about the front one?") can retrieve poorly. Query rewriting would fix this.
7. Windows/EDB-specific build. pgvector ships no Windows binaries for PG18 and
   was compiled from source; see the README. Not portable as-is.

## 8. Build status

Built: schema and pgvector on PG18, resumable ingestion with retry and fallback,
retrieval, answer synthesis, the five-tool MCP server, the CLI, and the chat UI.
Ingestion is verified end-to-end on the prototype pages; the full ingest is a
user-run step.

Deliberately not built for a private MVP: auth, remote/HTTP transport, and
multi-tenant hosting.
