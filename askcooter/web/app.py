"""FastAPI backend for the Ask Cooter chat UI.

Serves a single-page chat at ``/`` and streams cited answers over SSE from
``/api/ask``. Launch with: ``python -m askcooter.cli web``

The answer stream emits newline-delimited SSE ``data:`` events, each a JSON
object with a ``type``:
  {"type": "sources", "sources": [...]}   once, first
  {"type": "token",   "text": "..."}       many
  {"type": "done"}                          once, last
  {"type": "error",   "message": "..."}     on failure
"""
from __future__ import annotations

import json
from pathlib import Path

import anthropic
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..answer import build_messages
from ..config import cfg
from ..retrieval import search_manual

app = FastAPI(title="Ask Cooter")
_INDEX_HTML = Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


class AskRequest(BaseModel):
    question: str
    limit: int | None = None


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/ask")
def api_ask(req: AskRequest) -> StreamingResponse:
    question = (req.question or "").strip()
    results = search_manual(question, limit=req.limit or 6) if question else []

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
            yield _sse({"type": "token", "text": "Ask me something about the Softail."})
            yield _sse({"type": "done"})
            return
        if not results:
            yield _sse({"type": "token", "text": "I couldn't find anything in the manual for that. Has it been ingested?"})
            yield _sse({"type": "done"})
            return

        system, user = build_messages(question, results)
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        try:
            with client.messages.stream(
                model=cfg.answer_model,
                max_tokens=1500,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for text in stream.text_stream:
                    yield _sse({"type": "token", "text": text})
        except Exception as e:  # noqa: BLE001 — surface to the UI rather than 500
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
        yield _sse({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream")
