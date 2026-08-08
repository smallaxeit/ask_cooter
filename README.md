# Ask Cooter

**Turn any PDF — even a scanned, text-free one — into a private, cited knowledge
expert.** Ask Cooter ingests a PDF, extracts clean text, tables, and figure
descriptions from every page with a vision model, embeds it into a vector store,
and answers questions about it with citations back to the exact source page —
through a CLI, a local chat UI, or an MCP server.

Because extraction is vision-based, it works on **scanned documents with no
selectable text** (the hard case), not just digital PDFs.

### Initial use case

The proof-of-concept corpus is a **Harley-Davidson Softail (1984–1999) service
manual** — 651 scanned pages, zero embedded text — turned into a mechanic's
assistant ("Ask Cooter") that answers repair questions and cites the page to open
for the original diagram or torque spec. The defaults in `.env.example` point at
that manual; nothing in the pipeline is motorcycle-specific: set `PDF_PATH` to any
PDF and re-run the ingest.

See [DESIGN.md](DESIGN.md) for the architecture and rationale.

## How it works

```
Any PDF (scanned images or digital text)
  → render each page to PNG            (PyMuPDF)
  → vision extraction (Claude)         → clean markdown + tables + figure text + specs
  → chunk + Voyage embeddings          → stored in Postgres/pgvector
Question → embed → pgvector similarity search → cited passages → answer (CLI / chat UI / MCP)
```

## Stack (as built)

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.13 | |
| Vision extraction | Anthropic Messages API, `claude-opus-5` (default) | structured JSON output; `EXTRACT_MODEL` swappable to `claude-sonnet-5` for a cheaper bulk run |
| Embeddings | Voyage `voyage-3.5`, 1024-dim | Anthropic has no embeddings API; separate signup |
| Vector store | PostgreSQL 18 + pgvector 0.8.6 | native Windows, **no Docker**; pgvector compiled from source (see `pgvector-build/`), HNSW cosine index |
| PDF rendering | PyMuPDF (`fitz`) | every page → PNG at 150 DPI (scanned or digital) |
| Serving | MCP (stdio) + CLI + local chat UI | 5 MCP tools; answers cite source pages |

## Prerequisites

- **Python 3.11+**
- **PostgreSQL 18** (installed at `C:\Program Files\PostgreSQL\18`, port **5433**)
  with the **pgvector** extension. pgvector ships no Windows binaries, so it's
  compiled from source (step 1) and installed with a script. The compiled `.dll`
  is **not committed**; build it locally. No Docker.
- **API keys**: `ANTHROPIC_API_KEY` (vision extraction) and `VOYAGE_API_KEY`
  (embeddings). Anthropic doesn't do embeddings, so Voyage is a separate signup.

## Setup (native, no Docker)

```bash
python -m venv .venv
. .venv/Scripts/activate            # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                 # then fill in the two API keys
```

**1. Build pgvector for PostgreSQL 18** (the compiled `.dll` isn't committed).
From an *x64 Native Tools Command Prompt for VS*:

```bat
git clone --branch v0.8.6 https://github.com/pgvector/pgvector.git
cd pgvector
set PGROOT=C:\Program Files\PostgreSQL\18
nmake /f Makefile.win
```

Copy the outputs into `pgvector-build\` (where the install script looks):

```powershell
Copy-Item pgvector\vector.dll, pgvector\vector.control, pgvector\sql\vector--*.sql pgvector-build\
```

> On PG18 the standard build links cleanly. (On PG17, EDB's build did not export
> `float_to_shortest_decimal_*`; a small shim defining those functions, added to
> `OBJS` in `Makefile.win`, is required. PG18 exports them, so no shim is needed.)

**2. Install pgvector into PostgreSQL 18** (copies the files into Program Files —
needs admin; the script self-elevates via UAC):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-pgvector.ps1
```

**3. Create the database + role + extension** (prompts for the `postgres`
superuser password; PG18 is on port 5433):

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -p 5433 -f scripts\bootstrap-db.sql
```

**4. Create the Ask Cooter tables:**

```bash
python -m askcooter.cli init-db
```

## Ingest a PDF (one-time, costs API money)

This renders every page of the configured PDF (`PDF_PATH`), runs each through the
vision model, embeds the text, and stores everything. It is **resumable** — re-run
the same command to retry any pages that failed, and it auto-retries the output
content-filter false positives with a model fallback.

**Recommended: prototype on a small page range first** to eyeball quality and cost:

```bash
python -m askcooter.cli ingest --start 88 --end 92      # example pages
python -m askcooter.cli query "primary chaincase oil"
```

Then run the whole document:

```bash
python -m askcooter.cli ingest
```

**Point it at a different PDF:** set `PDF_PATH` in `.env`. One PDF per database —
to switch corpora, use a fresh `DATABASE_URL` (or truncate `pages`/`chunks` and
re-`init-db`), since results are ranked across whatever is in the DB.

Cost note: extraction is one vision call per page (651 for the Softail manual).
`EXTRACT_MODEL` defaults to `claude-opus-5` (highest fidelity); set
`EXTRACT_MODEL=claude-sonnet-5` in `.env` for a much cheaper run — usually fine for
OCR-style extraction. Embeddings (Voyage) are cents.

## Ask a question (direct, cited answer)

`ask` retrieves the relevant passages, hands them to Claude, and returns a direct
answer with source-page citations:

```bash
python -m askcooter.cli ask "how much oil does the primary chaincase hold?"
```

`query` is the raw retrieval view (top matching passages, no synthesis) — useful
for debugging what the vector search finds:

```bash
python -m askcooter.cli query "how do I test the starter solenoid?"
python -m askcooter.cli sections
```

## Chat UI

A local single-page chat, streaming answers with citations:

```bash
python -m askcooter.cli web            # → http://127.0.0.1:8000
```

Self-contained (no external assets), light/dark aware. It uses `ANSWER_MODEL` and
your keys from `.env`. Bind elsewhere with `--host` / `--port`.

## Accessing the database

The data lives in PostgreSQL 18 (`askcooter` DB, role `cooter`, port **5433**).

- **psql shell:** `powershell -ExecutionPolicy Bypass -File scripts\db-shell.ps1`
  (or `& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U cooter -p 5433 -d askcooter`)
- **pgAdmin 4** (installed by the EDB Postgres installer): add a server →
  host `localhost`, port `5433`, database `askcooter`, user `cooter`.
- **Any GUI** (DBeaver, TablePlus): connect to `localhost:5433 / askcooter / cooter`.

Handy queries: `SELECT count(*) FROM pages;` · `SELECT pdf_page, printed_page, section FROM pages ORDER BY pdf_page;` · `SELECT count(*) FROM chunks;`

## Use as an MCP server

Run over stdio:

```bash
python -m askcooter.cli serve
```

Register with Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ask-cooter": {
      "command": "python",
      "args": ["-m", "askcooter.cli", "serve"],
      "cwd": "C:/app/AskCooter",
      "env": {
        "DATABASE_URL": "postgresql://cooter:cooter@localhost:5433/askcooter",
        "VOYAGE_API_KEY": "pa-..."
      }
    }
  }
}
```

(The server needs `VOYAGE_API_KEY` to embed incoming queries and `DATABASE_URL`
to reach Postgres. It also needs `ANTHROPIC_API_KEY` if the `ask` tool is used —
add it to the `env` block above. `search_manual` alone does not require it, since
the MCP host does the synthesis.)

### MCP tools

| Tool | Purpose |
|---|---|
| `ask(question, limit)` | Direct, cited answer (retrieval + Claude synthesis) |
| `search_manual(query, limit, component)` | Semantic search; returns cited passages |
| `get_page(pdf_page)` | Full extracted content of one page + specs + figures |
| `get_torque_spec(component)` | Structured spec lookup (torque, clearances, capacities) |
| `list_sections()` | Section table of contents with page ranges |

## Project layout

```
askcooter/
  config.py            env-based settings
  db.py                pgvector connection + schema init
  schema.sql           DDL (pages, chunks, user_history)
  ingest/
    render.py          PDF page → PNG
    extract.py         Claude vision → structured JSON
    chunk.py           structure-aware chunking
    embed.py           Voyage embeddings
    pipeline.py        resumable orchestration
  retrieval.py         query embed + pgvector search + spec/section lookups
  answer.py            retrieval + Claude synthesis (the `ask` layer)
  mcp_server.py        FastMCP server (5 tools)
  cli.py               init-db / ingest / ask / query / sections / web / serve
  web/
    app.py             FastAPI backend (streaming SSE)
    index.html         single-page chat UI
scripts/
  install-pgvector.ps1 copy the built extension into PG18 (admin)
  bootstrap-db.sql     create role/db/extension
  db-shell.ps1         open a psql shell to the DB
```

## Notes & limits

- **Page numbers:** `pdf_page` is 0-based internally; the CLI and tools print the
  1-based PDF page plus the manual's own printed label so you can always find the
  original.
- **Copyright:** your source PDF may be copyrighted (the Softail manual is).
  Keeping Ask Cooter private/personal is the intended use — see DESIGN.md §6 before
  considering any public deployment.
- **User history:** the `user_history` table exists but is unused in the MVP
  (designed forward-compatible; no auth).

## License

**PolyForm Noncommercial License 1.0.0** — see [LICENSE](LICENSE). Copyright 2026
SmallAxeIT. Free to use, modify, and share for **noncommercial** purposes only;
commercial use is not granted.

The Harley-Davidson Softail service manual is **not** part of this repository and
is not covered by this license; it is copyrighted by its publisher and excluded
from version control (see `.gitignore`).

## Known limitations & tech debt

- **Embedding dimension is hardcoded in `schema.sql` (`VECTOR(1024)`).** It must
  match `EMBED_DIM` and the Voyage model's native dimension. Changing `VOYAGE_MODEL`
  to a different-dimension model requires editing the DDL and a full re-embed; there
  is no migration path.
- **Ingest is sequential.** ~1–2s per page (≈15–25 min for 651 pages). A thread pool
  over pages would parallelize it. Retry is re-running the command (per-page commit +
  skip); the Anthropic SDK retries 429/5xx transient failures.
- **Citation fidelity is prompt-enforced, not guaranteed.** `ask` / `answer.py`
  synthesize a cited answer server-side; `search_manual` returns raw passages for an
  MCP host to synthesize. In both paths the model is instructed to cite; there is no
  post-check that every claim maps to a retrieved page.
- **Chunking uses a char≈token approximation** (`len//4`). The value is stored as
  metadata only; chunk boundaries are character-bounded, not token-based.
- **Windows/EDB-specific build.** The pgvector build and install scripts hardcode
  `C:\Program Files\PostgreSQL\18` and the MSVC toolchain. Not portable as-is.
- **No automated tests.** Verification is manual (compile, render, live query).
- **`printed_page` is model-read per page.** OCR misreads of the printed label are
  possible; `pdf_page` is authoritative for jumping.
