-- Ask Cooter schema. Run via: python -m askcooter.cli init-db
-- Embedding dimension (VECTOR(1024)) must match EMBED_DIM / the Voyage model.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per PDF page. Stores the vision-extracted text plus structured
-- specs/diagrams and the traceability numbers (see DESIGN.md §3.5).
CREATE TABLE IF NOT EXISTS pages (
    id             BIGSERIAL PRIMARY KEY,
    pdf_page       INTEGER NOT NULL UNIQUE,   -- position in the PDF file (for jumping)
    printed_page   TEXT,                      -- manual's own label, e.g. '3-14' (nullable)
    section        TEXT,
    component_tags TEXT[] NOT NULL DEFAULT '{}',
    image_path     TEXT,                      -- rendered PNG on disk
    markdown       TEXT NOT NULL,             -- clean extracted text (chunk source)
    specs          JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{name,value,unit,notes}]
    diagrams       JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{figure,title,description}]
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pages_pdf_page_idx ON pages (pdf_page);
CREATE INDEX IF NOT EXISTS pages_section_idx  ON pages (section);

-- Retrieval units. One page yields one or more chunks.
CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    page_id      BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    pdf_page     INTEGER NOT NULL,
    chunk_index  INTEGER NOT NULL,
    content      TEXT NOT NULL,
    embedding    VECTOR(1024),
    token_count  INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (page_id, chunk_index)
);

-- Approximate-nearest-neighbour index for cosine similarity search.
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

-- FUTURE (designed now, unused in MVP): per-user history.
-- No auth in MVP; keyed by an opaque client-supplied token (see DESIGN.md §4).
CREATE TABLE IF NOT EXISTS user_history (
    id              BIGSERIAL PRIMARY KEY,
    user_token      TEXT NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT,
    cited_pdf_pages INTEGER[] NOT NULL DEFAULT '{}',
    bike_profile    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_history_token_idx ON user_history (user_token);
