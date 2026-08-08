"""Answer synthesis: retrieval + Claude -> a direct, cited answer.

This is the layer that turns "a bunch of passages" into an actual answer. It
retrieves the most relevant manual chunks, hands them to Claude, and asks for a
grounded answer that cites the source pages. Claude is instructed to answer only
from the excerpts and to say so (and point to where it likely is) when they don't
contain the answer, rather than inventing a spec.
"""
from __future__ import annotations

from dataclasses import dataclass

import anthropic

from .config import cfg
from .retrieval import SearchResult, search_manual

SYSTEM = """You are Ask Cooter, an expert mechanic assistant for the Harley-Davidson Softail (1984-1999).

Answer the user's question using ONLY the numbered manual excerpts provided in the user message.
- Lead with a direct, specific answer to what was asked.
- Cite the source page(s) inline as [PDF p.N], using the page numbers shown on each excerpt.
- Preserve exact specs, torque values, capacities, and step order verbatim — do not paraphrase numbers.
- If the excerpts do not contain the answer, say so plainly and point to where it likely lives
  (e.g. a capacities or torque-spec table), rather than guessing or using outside knowledge.
- Be practical and concise. This is for someone working on the bike."""


def build_messages(question: str, results: list[SearchResult]) -> tuple[str, str]:
    """Return (system_prompt, user_message) for a synthesis call."""
    blocks = []
    for i, r in enumerate(results, 1):
        printed = f" / printed {r.printed_page}" if r.printed_page else ""
        section = f" — {r.section}" if r.section else ""
        blocks.append(f"[Excerpt {i} — PDF p.{r.pdf_page + 1}{printed}{section}]")
        blocks.append(r.content.strip())
        blocks.append("")
    context = "\n".join(blocks).strip()
    user = f"Question: {question}\n\nManual excerpts:\n\n{context}"
    return SYSTEM, user


def build_chat_messages(
    question: str,
    results: list[SearchResult],
    history: list[dict] | None = None,
    *,
    max_history: int = 6,
) -> tuple[str, list[dict]]:
    """Return (system_prompt, messages) for a multi-turn synthesis call.

    Prior turns are included so follow-up questions have context. Retrieval still
    runs on the current question only; the retrieved passages are attached to the
    final user turn. The message list is normalized to start with a user turn.
    """
    system, user = build_messages(question, results)
    messages: list[dict] = []
    for turn in (history or [])[-max_history:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user})
    # Anthropic requires the first message to be a user turn.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return system, messages


@dataclass
class AnswerResult:
    answer: str
    sources: list[SearchResult]


def answer(question: str, *, limit: int | None = None) -> AnswerResult:
    """Retrieve, synthesize, and return a cited answer (non-streaming)."""
    results = search_manual(question, limit=limit or 6)
    if not results:
        return AnswerResult(
            answer="I couldn't find anything in the manual for that. Has it been ingested yet?",
            sources=[],
        )

    system, user = build_messages(question, results)
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=cfg.answer_model,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":
        text = "I can't help with that request."
    else:
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return AnswerResult(answer=text, sources=results)
