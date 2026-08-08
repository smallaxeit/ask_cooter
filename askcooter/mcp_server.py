"""Ask Cooter MCP server.

Exposes the manual as MCP tools over stdio (local, private use — see DESIGN.md
§3.3). Point Claude Desktop / Claude Code at this module:

    python -m askcooter.mcp_server

Every tool return includes source page numbers so the assistant can cite them
and the user can open the PDF to the original scan.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import retrieval

mcp = FastMCP("ask-cooter")

_INTRO = (
    "Ask Cooter is grounded in the Harley-Davidson Softail 1984-1999 repair "
    "manual. Answer only from the returned excerpts, and always cite the source "
    "page(s) so the user can open the PDF to the original."
)


@mcp.tool()
def search_manual(query: str, limit: int = 5, component: str = "") -> str:
    """Search the repair manual for passages relevant to a question.

    Args:
        query: What you want to find (e.g. "primary chaincase oil capacity").
        limit: Max passages to return (default 5).
        component: Optional component tag filter (e.g. "clutch", "carburetor").
    """
    results = retrieval.search_manual(query, limit=limit, component=component or None)
    if not results:
        return "No matching passages found in the manual."

    blocks = [_INTRO, ""]
    for i, r in enumerate(results, 1):
        blocks.append(f"### Result {i} — {r.citation()}  (similarity {r.score:.2f})")
        blocks.append(r.content.strip())
        blocks.append("")
    return "\n".join(blocks).strip()


@mcp.tool()
def ask(question: str, limit: int = 6) -> str:
    """Get a direct, cited answer to a repair question.

    Retrieves the most relevant manual passages and synthesizes a grounded answer
    with source-page citations. Use this for a one-shot answer; use search_manual
    when you want the raw passages to reason over yourself.

    Args:
        question: The repair question, e.g. "primary chaincase oil capacity".
        limit: How many passages to retrieve for context (default 6).
    """
    from .answer import answer as _answer

    res = _answer(question, limit=limit)
    if not res.sources:
        return res.answer
    srcs = "; ".join(s.citation() for s in res.sources)
    return f"{res.answer}\n\nSources: {srcs}"


@mcp.tool()
def get_page(pdf_page: int) -> str:
    """Return the full extracted content of one manual page.

    Args:
        pdf_page: 0-based position in the PDF (as reported by search results;
            the printed page label is shown in the output).
    """
    page = retrieval.get_page(pdf_page)
    if not page:
        return f"No page {pdf_page} found. Has the manual been ingested?"

    printed = f" (printed {page.printed_page})" if page.printed_page else ""
    out = [f"# PDF page {page.pdf_page + 1}{printed}"]
    if page.section:
        out.append(f"_Section: {page.section}_")
    out.append("")
    out.append(page.markdown.strip())

    if page.specs:
        out.append("\n## Specs on this page")
        for s in page.specs:
            unit = f" {s['unit']}" if s.get("unit") else ""
            notes = f" — {s['notes']}" if s.get("notes") else ""
            out.append(f"- **{s['name']}**: {s['value']}{unit}{notes}")

    if page.diagrams:
        out.append("\n## Figures on this page")
        for d in page.diagrams:
            fig = f"Fig {d['figure']}: " if d.get("figure") else ""
            title = f"{d['title']} — " if d.get("title") else ""
            out.append(f"- {fig}{title}{d['description']}")

    if page.image_path:
        out.append(f"\n_Original scan: {page.image_path}_")
    return "\n".join(out)


@mcp.tool()
def get_torque_spec(component: str) -> str:
    """Look up torque values and other specs for a component or system.

    Args:
        component: Component/keyword, e.g. "cylinder head bolt", "axle nut".
    """
    specs = retrieval.find_specs(component)
    if not specs:
        return f"No specs found matching '{component}'."

    lines = [f"Specs matching '{component}':", ""]
    for s in specs:
        printed = f" (printed {s['printed_page']})" if s.get("printed_page") else ""
        unit = f" {s['unit']}" if s.get("unit") else ""
        notes = f" — {s['notes']}" if s.get("notes") else ""
        lines.append(
            f"- **{s['name']}**: {s['value']}{unit}{notes}  "
            f"[PDF p.{s['pdf_page'] + 1}{printed}]"
        )
    return "\n".join(lines)


@mcp.tool()
def list_sections() -> str:
    """List the manual's sections with their PDF page ranges (table of contents)."""
    sections = retrieval.list_sections()
    if not sections:
        return "No sections found. Has the manual been ingested?"
    lines = ["Manual sections (PDF page ranges):", ""]
    for s in sections:
        lines.append(
            f"- {s['section']}  — PDF p.{s['first_pdf_page'] + 1}"
            f"–{s['last_pdf_page'] + 1} ({s['pages']} pages)"
        )
    return "\n".join(lines)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
