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

from .. import history
from ..answer import build_chat_messages
from ..config import cfg
from ..db import connect
from ..retrieval import get_page, search_manual

app = FastAPI(title="Ask Cooter")
_INDEX_PATH = Path(__file__).with_name("index.html")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # Read per request so UI edits show on reload without a server restart.
    return _INDEX_PATH.read_text(encoding="utf-8")


class Turn(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str
    limit: int | None = None
    history: list[Turn] | None = None
    bike: str | None = None
    user_token: str | None = None


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/ask")
def api_ask(req: AskRequest) -> StreamingResponse:
    question = (req.question or "").strip()
    results = search_manual(question, limit=req.limit or 6) if question else []
    chat_history = [t.model_dump() for t in (req.history or [])]
    bike = (req.bike or "").strip() or None
    user_token = (req.user_token or "").strip() or None

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

        system, messages = build_chat_messages(question, results, chat_history, bike=bike)
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        parts: list[str] = []
        try:
            with client.messages.stream(
                model=cfg.answer_model,
                max_tokens=2048,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    parts.append(text)
                    yield _sse({"type": "token", "text": text})
        except Exception as e:  # noqa: BLE001 — surface to the UI rather than 500
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})

        answer_text = "".join(parts).strip()
        if answer_text and user_token:
            try:
                history.record(
                    user_token, question, answer_text,
                    [s["pdf_page"] for s in sources], bike,
                )
            except Exception:  # noqa: BLE001 — never let history writes break the answer
                pass
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


@app.get("/api/meta")
def api_meta() -> dict:
    """Ingested page count and 1-based min/max PDF page (for flip bounds)."""
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT count(*), min(pdf_page), max(pdf_page) FROM pages")
        n, mn, mx = cur.fetchone()
    return {
        "pages": n or 0,
        "min_page": (mn + 1) if mn is not None else None,
        "max_page": (mx + 1) if mx is not None else None,
    }


@app.get("/api/history")
def api_history(user_token: str = "", limit: int = 100) -> dict:
    """Saved Q&A for a client token (most recent first), including answers."""
    return {"items": history.list_for(user_token, limit)}


@app.delete("/api/history")
def api_history_clear(user_token: str = "") -> dict:
    """Delete all saved history for a client token."""
    return {"deleted": history.clear(user_token)}
