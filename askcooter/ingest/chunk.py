"""Structure-aware chunking of a page's extracted Markdown.

Manual pages are short, so most pages yield 1-2 chunks. We split on blank lines
(paragraph/section boundaries) and pack paragraphs up to a target size, keeping
procedure steps and tables intact within a chunk where possible.
"""
from __future__ import annotations

# Character targets (~4 chars/token → ~150-400 tokens/chunk).
TARGET_CHARS = 1400
MAX_CHARS = 2200


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_markdown(markdown: str) -> list[str]:
    """Split page markdown into retrieval chunks. Never returns an empty list
    for non-empty input."""
    text = (markdown or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text]

    chunks: list[str] = []
    buf: list[str] = []
    size = 0

    for para in paragraphs:
        para_len = len(para)
        # A single oversized paragraph (e.g. a big table) becomes its own chunk.
        if para_len >= MAX_CHARS:
            if buf:
                chunks.append("\n\n".join(buf))
                buf, size = [], 0
            chunks.append(para)
            continue

        if size + para_len > MAX_CHARS and buf:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0

        buf.append(para)
        size += para_len + 2

        if size >= TARGET_CHARS:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0

    if buf:
        chunks.append("\n\n".join(buf))

    return chunks


def token_count(text: str) -> int:
    return _approx_tokens(text)
