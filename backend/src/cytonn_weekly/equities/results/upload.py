from __future__ import annotations

import io
import re
from typing import Any

import pdfplumber

from cytonn_weekly.equities import companies
from cytonn_weekly.equities.results.statement import SOURCE_DISAGREES, StatementRefused, read_statement

MIN_TEXT = 200
SCANNED = "this is a scanned page; upload the PDF from the bank's website, which has a text layer"
NOT_CBK = "not the CBK financial statements page"
_BLOCKS = ("sfp", "income", "other:capital")   # the three section headings, and the capital block of section III


class Refused(ValueError):
    pass


def _words(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9&]+", " ", text.lower()).split()) + " "


def find_bank(text: str) -> companies.Company:
    """The one bank whose name or alias the page's title or entity headers print."""
    words = _words(text)
    found = [c for c in companies.load() if c.kind == "bank"
             and any(_words(n).strip() and _words(n) in words for n in (c.name, *c.aliases))]
    if len(found) != 1:
        named = " ".join(text.split())[:200]
        raise Refused(f"the bank on this page is not one the tool knows (the page names: {named})" if not found else
                      f"the page names more than one bank ({', '.join(c.name for c in found)}); upload one bank's file at a time")
    return found[0]


def read(data: bytes) -> dict[str, Any]:
    """Read one bank's quarterly statements: what is stored with the file. Refused, with the reason, if it is not one."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    if sum(len(t.strip()) for t in pages) < MIN_TEXT:
        raise Refused(SCANNED)
    try:
        st = read_statement(io.BytesIO(data), "")
    except StatementRefused:
        raise Refused(NOT_CBK)
    if any(b not in st.block_entities for b in _BLOCKS):
        raise Refused(NOT_CBK)
    bank = find_bank(" ".join(pages[0].splitlines()[:3] + st.entities))
    disagree = [f for f in st.flags if f["kind"] == SOURCE_DISAGREES]
    return {
        "bank": bank.name, "ticker": bank.ticker, "period": max(st.periods).isoformat(), "entities": st.entities,
        "group_entity": st.group_entity, "checks_passed": not st.flags, "flag_count": len(disagree),
        "flags": [f"{f['entity']}, {f['period']:%d %b %Y}: {f['check']}" for f in disagree],
        "stored_name": f"bank_results_{(bank.ticker or bank.id).lower()}.pdf",
    }
