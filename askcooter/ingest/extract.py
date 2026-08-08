"""Vision extraction: a scanned page image -> clean structured content.

Uses the Anthropic Messages API with an image block and a JSON-schema output
format so the response is guaranteed parseable. This is where answer accuracy is
won or lost (see DESIGN.md §2), so the prompt is explicit about tables, diagrams,
torque specs, and the printed page label.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from ..config import cfg

# JSON schema the model must fill in. Structured-output constraints: every object
# needs additionalProperties:false and lists all keys in `required`; optional
# values are expressed as nullable types rather than omitted keys.
PAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "printed_page": {
            "type": ["string", "null"],
            "description": "The page label printed on the page itself, e.g. '3-14' or '541'. Null if none is visible.",
        },
        "section": {
            "type": ["string", "null"],
            "description": "The running section/chapter header, e.g. 'LUBRICATION, MAINTENANCE AND TUNE-UP'. Null if none.",
        },
        "component_tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Lowercase component/system keywords relevant to this page, e.g. ['clutch','primary drive','oil'].",
        },
        "markdown": {
            "type": "string",
            "description": "The full page content as clean Markdown: body text, procedures with step numbers preserved, and any TABLES reconstructed as Markdown tables. Include a short description of each figure/diagram inline where it appears.",
        },
        "specs": {
            "type": "array",
            "description": "Any explicit specifications on the page (torque values, clearances, capacities, electrical readings).",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["name", "value", "unit", "notes"],
            },
        },
        "diagrams": {
            "type": "array",
            "description": "Figures, photos, exploded views, and wiring/test diagrams on the page.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "figure": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                },
                "required": ["figure", "title", "description"],
            },
        },
    },
    "required": ["printed_page", "section", "component_tags", "markdown", "specs", "diagrams"],
}

PROMPT = """You are digitizing one scanned page of a Harley-Davidson Softail (1984-1999) service manual.

Transcribe this page faithfully and completely. Rules:
- Reconstruct every TABLE as a Markdown table — torque-spec and clearance tables are the highest-value content and must be exact.
- Preserve numbered/lettered procedure steps in order.
- For each diagram, photo, exploded view, or wiring/test diagram, write a clear text description (what it shows, part callouts, wire colors, connections) so it is searchable.
- Capture the printed page number exactly as shown on the page (it usually differs from the PDF position).
- Pull every explicit spec (torque, clearance, capacity, voltage/resistance reading) into the `specs` list.
- Do not invent content that is not on the page. If the page is blank or a cover/index, return empty lists and a short markdown note.

Return only the structured JSON."""


@dataclass
class PageExtract:
    printed_page: str | None
    section: str | None
    component_tags: list[str]
    markdown: str
    specs: list[dict] = field(default_factory=list)
    diagrams: list[dict] = field(default_factory=list)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=cfg.anthropic_api_key)


def extract_page(
    image_path: Path,
    *,
    client: anthropic.Anthropic | None = None,
    model: str | None = None,
) -> PageExtract:
    """Run vision extraction on one rendered page image."""
    client = client or _client()
    b64 = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")

    resp = client.messages.create(
        model=model or cfg.extract_model,
        max_tokens=8000,
        # effort low: transcription, not deep reasoning. Structured output keeps
        # the response constrained to the schema (also avoids stray tag leakage).
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": PAGE_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    if resp.stop_reason == "refusal":
        raise RuntimeError(
            f"Extraction refused for {image_path.name}: "
            f"{getattr(resp.stop_details, 'category', None)}"
        )

    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise RuntimeError(f"No text block returned for {image_path.name}")

    data = json.loads(text)
    return PageExtract(
        printed_page=data.get("printed_page"),
        section=data.get("section"),
        component_tags=data.get("component_tags") or [],
        markdown=data.get("markdown") or "",
        specs=data.get("specs") or [],
        diagrams=data.get("diagrams") or [],
    )
