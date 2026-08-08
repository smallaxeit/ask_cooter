"""FastAPI backend for the Ask Cooter chat UI.

Serves a single-page chat at ``/`` and streams cited answers over SSE from
``/api/ask``. Launch with: ``python -m askcooter.cli web``

Endpoints:
  GET  /                      the chat page
  POST /api/ask               stream a cited answer (SSE); accepts history
  GET  /api/page/{n}          extracted content of PDF page n (1-based)
  GET  /api/page-image/{n}    the rendered scan of PDF page n (1-based)

The answer stream emits newline-delimited SSE ``data:`` events, each a JSON
object with a ``type``: ``sources`` (once, first), ``token`` (many), ``error``
(on failure), ``done`` (once, last).
"""
from __future__ import annotations

import json
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from ..answer import build_chat_messages
from ..config import cfg
from ..retrieval import get_page, search_manual

app = FastAPI(title="Ask Cooter")
_INDEX_HTML = Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


class Turn(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str
    limit: int | None = None
    history: list[Turn] | None = None


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/ask")
def api_ask(req: AskRequest) -> StreamingResponse:
    question = (req.question or "").strip()
    results = search_manual(question, limit=req.limit or 6) if question else []
    history = [t.model_dump() for t in (req.history or [])]

    def gen():
        sources = [
            {
                "pdf_page": r.pdf_page + 1,
                "printed_page": r.printed_page,
                "section": r.section,
                "citation": r.citation(),
                "score": round(r.score, 3),
            }
            for r in results
        ]
        yield _sse({"type": "sources", "sources": sources})

        if not question:
            yield _sse({"type": "token", "text": "Ask a question about the manual."})
            yield _sse({"type": "done"})
            return
        if not results:
            yield _sse({"type": "token", "text": "Nothing in the manual matched that. Has it been ingested?"})
            yield _sse({"type": "done"})
            return

        system, messages = build_chat_messages(question, results, history)
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        try:
            with client.messages.stream(
                model=cfg.answer_model,
                max_tokens=2048,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield _sse({"type": "token", "text": text})
        except Exception as e:  # noqa: BLE001 — surface to the UI rather than 500
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
        yield _sse({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/page/{pdf_page}")
def api_page(pdf_page: int) -> dict:
    """Extracted content of a page. ``pdf_page`` is 1-based (as shown in the UI)."""
    page = get_page(pdf_page - 1)
    if not page:
        raise HTTPException(status_code=404, detail="page not found")
    has_image = bool(page.image_path and Path(page.image_path).exists())
    return {
        "pdf_page": page.pdf_page + 1,
        "printed_page": page.printed_page,
        "section": page.section,
        "markdown": page.markdown,
        "specs": page.specs or [],
        "diagrams": page.diagrams or [],
        "has_image": has_image,
    }


@app.get("/api/page-image/{pdf_page}")
def api_page_image(pdf_page: int) -> Response:
    """The rendered scan of a page. ``pdf_page`` is 1-based."""
    page = get_page(pdf_page - 1)
    if not page or not page.image_path:
        raise HTTPException(status_code=404, detail="no image")
    path = Path(page.image_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="image file missing")
    return Response(content=path.read_bytes(), media_type="image/png")
