"""Each weekly section's summary: the paragraph block the CMS stores beside the section's body.

On cytonnreport.com every section has a ``body`` and a ``summary``; the website builds the
issue's Executive Summary from the summaries.  Read from #38.2026: a summary is the
section's own lead paragraphs, 1,500 to 3,000 characters (Fixed Income: the T-bills and
T-bonds paragraphs and the week's highlight; Equities: the market paragraphs and the first
highlight; Real Estate and Digital Payments: the opening of each item; Focus: its opening).
Company Updates has none.

So a summary here is composed, never drafted: no model is called.  Fixed Income and
Equities compose theirs when they are built (their lead paragraphs are computed).  For the
drafted sections it is the opening paragraph of each drafted piece, in order, up to the
limit, never cut inside a paragraph.
"""

from __future__ import annotations

from typing import Any

LIMIT = 3000


def _first_paragraph(text: str) -> str:
    return next((" ".join(p.split()) for p in (text or "").split("\n\n") if p.strip()), "")


def _fit(paragraphs: list[str], limit: int = LIMIT) -> str:
    out: list[str] = []
    for p in paragraphs:
        if p and sum(len(x) + 2 for x in out) + len(p) <= limit:
            out.append(p)
    return "\n\n".join(out)


def section_summary(section: dict[str, Any]) -> str:
    """The section content's summary text ("" when it has none, as Company Updates)."""
    if isinstance(section.get("summary"), str):
        return section["summary"]
    if "blocks" in section:
        return _fit([_first_paragraph(b.get("body_md", "")) for b in section["blocks"] if b.get("kind") == "narrative"])
    # The weekly Digital Payments shape: highlights as items.
    return _fit([_first_paragraph(i.get("body_md", "")) for i in section.get("items", []) if i.get("kind") == "highlight"])
