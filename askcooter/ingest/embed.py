"""Voyage AI embeddings.

Anthropic doesn't provide embeddings; Voyage is the design choice (see DESIGN.md).
Document chunks and query strings use different ``input_type`` for best retrieval.
"""
from __future__ import annotations

import voyageai

from ..config import cfg

_BATCH = 128


def _client() -> voyageai.Client:
    return voyageai.Client(api_key=cfg.voyage_api_key)


def embed_documents(
    texts: list[str], *, client: voyageai.Client | None = None
) -> list[list[float]]:
    """Embed chunk texts (input_type='document'). Batched for throughput."""
    client = client or _client()
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        result = client.embed(
            batch,
            model=cfg.voyage_model,
            input_type="document",
            output_dimension=cfg.embed_dim,
        )
        out.extend(result.embeddings)
    return out


def embed_query(text: str, *, client: voyageai.Client | None = None) -> list[float]:
    """Embed a single user query (input_type='query')."""
    client = client or _client()
    result = client.embed(
        [text],
        model=cfg.voyage_model,
        input_type="query",
        output_dimension=cfg.embed_dim,
    )
    return result.embeddings[0]
