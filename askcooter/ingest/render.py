"""Render scanned PDF pages to PNG images.

The source manual has no embedded text (verified: ~0 extractable chars), so
every page is rasterized and handed to a vision model downstream.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from ..config import cfg


def page_image_path(pdf_page: int) -> Path:
    """Deterministic on-disk path for a rendered page (0-based pdf_page)."""
    return cfg.image_dir / f"page_{pdf_page:04d}.png"


def open_pdf() -> fitz.Document:
    if not cfg.pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {cfg.pdf_path.resolve()}")
    return fitz.open(cfg.pdf_path)


def render_page(doc: fitz.Document, pdf_page: int, *, overwrite: bool = False) -> Path:
    """Render one page to PNG at RENDER_DPI. Returns the image path.

    Skips work if the image already exists (unless ``overwrite``).
    """
    out = page_image_path(pdf_page)
    if out.exists() and not overwrite:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    pix = doc[pdf_page].get_pixmap(dpi=cfg.render_dpi)
    pix.save(out)
    return out


def page_count() -> int:
    with open_pdf() as doc:
        return doc.page_count
