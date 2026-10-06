"""JSON shape of a CoordinatorReview for the web app.

The web app never re-derives anything the pipeline already knows, so the things the
Streamlit screen computed on the fly are computed here once:

* the table is display-formatted by fetcher.format_table_rows (the stored section holds
  raw fetcher rows, and the report's own string conventions live in that function);
* ``is_dev_draft``: any ``drafted_by`` starting with ``"local:"`` means NOT FOR PUBLICATION;
* which table rows the checker flagged, per-status counts, resolved / unresolved totals;
* each review item's ``index``, its position in ``review_items``, which is how the
  write endpoints address it.

Every section except the weekly Digital Payments stores generic blocks whose tables are
already display-formatted (common/review.py), so ``_serialize_blocks`` passes them
through; the review's top level is the same shape for every section, plus
``section_slug``, ``section_title``, and the report it belongs to (``report_type``,
``report_title``, ``period``).

Nothing here mutates the review.
"""

import math
import re
from typing import Any

from cytonn_weekly.digital_payments.coordinator_review import (
    CLEAN, FIX_NEEDED, FLAGGED, NOT_AUTO_VERIFIED, TABLE_ROW, CoordinatorReview,
)
from cytonn_weekly.digital_payments.fetcher import format_table_rows
from cytonn_weekly.digital_payments.highlights import N_HIGHLIGHTS
from cytonn_weekly.report_sections import section_slug, spec_for
from cytonn_weekly.report_types import TYPES, WEEKLY

LOCAL_PREFIX = "local:"
DEV_MODE_LABEL = "DEV MODE DRAFT (local model): NOT FOR PUBLICATION OR CIRCULATION"
TABLE_TITLE = "Digital Payments NYSE and LSE Stock Performance"

_HIGHLIGHT_FIELDS = (
    "numeral", "kind", "headline", "headline_md", "body_md", "claims", "warnings",
    "company", "search_scope", "ir_domain", "drafted_by",
)
_STATUSES = (FLAGGED, NOT_AUTO_VERIFIED, CLEAN)


def is_dev_draft(review: CoordinatorReview) -> bool:
    """True when any highlight, narrative piece or the outlook was drafted by the local (dev-only) provider."""
    sec = review.section
    drafted_by = {i.get("drafted_by") for i in sec.get("items", []) if i.get("kind") == "highlight"}
    drafted_by |= {b.get("drafted_by") for b in sec.get("blocks", []) if b.get("kind") == "narrative"}
    # Executive Summary: a local piece anywhere in an included section marks it, carried or not.
    drafted_by |= {p.get("drafted_by") for c in sec.get("not_covered", []) for p in c.get("dev_pieces", [])}
    drafted_by.add((sec.get("outlook") or {}).get("drafted_by"))
    return any(str(d).startswith(LOCAL_PREFIX) for d in drafted_by)


def _flagged_tickers(review: CoordinatorReview) -> set[str]:
    """Tickers of flagged table rows; a row's ref is "Visa (V)", or a bare ticker."""
    found = set()
    for item in review.review_items:
        if item.kind == TABLE_ROW and item.status == FLAGGED:
            m = re.search(r"\(([^()]+)\)\s*$", item.ref)
            found.add(m.group(1) if m else item.ref)
    return found


def _json_safe(value: Any) -> Any:
    """Non-finite floats are not valid JSON; keep them as their text ("nan", "inf") rather than fail."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _serialize_section(review: CoordinatorReview) -> dict[str, Any]:
    sec = review.section
    flagged = _flagged_tickers(review)
    items: list[dict[str, Any]] = []
    for it in sec.get("items", []):
        if it.get("kind") == "stock_table":
            raw = it.get("rows", [])
            rows = [
                {**shown, "flagged": shown["ticker"] in flagged, "error": src.get("error")}
                for shown, src in zip(format_table_rows(raw), raw)
            ]
            items.append({"numeral": it.get("numeral"), "kind": "stock_table", "title": TABLE_TITLE, "rows": rows})
        else:
            items.append({k: it.get(k) for k in _HIGHLIGHT_FIELDS if k in it})
    outlook = sec.get("outlook") or {}
    stats = outlook.get("stats") or {}
    return {
        "week_start": sec.get("week_start"),
        "week_end": sec.get("week_end"),
        "highlights_found": sum(1 for i in items if i.get("kind") == "highlight"),
        "highlights_expected": N_HIGHLIGHTS,
        "shortfall": sec.get("shortfall", 0),
        "warnings": list(sec.get("warnings", [])),
        "items": items,
        "outlook": {
            "text_md": outlook.get("text_md", ""),
            "stats": [{"key": k, "value": str(v)} for k, v in stats.items()],
            "warnings": list(outlook.get("warnings", [])),
            "drafted_by": outlook.get("drafted_by"),
        },
    }


_TABLE_FIELDS = ("numeral", "kind", "id", "title", "columns", "key_field", "rows", "source")
_NARRATIVE_FIELDS = ("numeral", "kind", "id", "topic", "headline", "body_md", "claims", "warnings",
                     "search_scope", "preferred_domains", "drafted_by",
                     # Executive Summary only: which approved section and run the piece was carried from.
                     "source_section", "source_run_id", "source_headline")
_UNAVAILABLE_FIELDS = ("numeral", "kind", "id", "title", "reason", "unblock")
_SUPPLIED_FIELDS = ("numeral", "kind", "id", "title", "body_md", "supplied_by")


def _flagged_rows(review: CoordinatorReview) -> set[str]:
    """``"<table id>/<row key>"`` of every table row a checker flag points at."""
    return {f.subject for i in review.review_items if i.kind == TABLE_ROW and isinstance(i.detail, list)
            for f in i.detail if f.scope == "table"}


def _serialize_blocks(review: CoordinatorReview) -> dict[str, Any]:
    sec = review.section
    flagged = _flagged_rows(review)
    blocks = []
    for b in sec.get("blocks", []):
        if b["kind"] == "table":
            out = {k: b.get(k) for k in _TABLE_FIELDS}
            key = b["key_field"]
            errors = {r[key]: r.get("error") for r in b.get("source_rows", [])}
            out["columns"] = [{"key": c["key"], "label": c["label"], "numeric": c.get("fmt", "text") != "text"}
                              for c in b["columns"]]
            out["rows"] = [{**r, "flagged": f"{b['id']}/{r[key]}" in flagged, "error": errors.get(r[key])}
                           for r in b.get("rows", [])]
            blocks.append(out)
        elif b["kind"] == "narrative":
            blocks.append({k: b.get(k) for k in _NARRATIVE_FIELDS})
        elif b["kind"] == "supplied":
            blocks.append({k: b.get(k) for k in _SUPPLIED_FIELDS})
        else:
            blocks.append({k: b.get(k) for k in _UNAVAILABLE_FIELDS})
    return {
        "week_start": sec.get("week_start"),
        "week_end": sec.get("week_end"),
        "period_start": sec.get("period_start"),
        "period_end": sec.get("period_end"),
        "topic": sec.get("topic"),
        "pieces_found": sec.get("pieces_found", 0),
        "pieces_expected": sec.get("pieces_expected", 0),
        "shortfall": sec.get("shortfall", 0),
        "warnings": list(sec.get("warnings", [])),
        "chart_notes": list(sec.get("chart_notes", [])),
        "chart_reference": sec.get("chart_reference"),
        # Executive Summary only: what the composition is, and what each included section holds that it leaves out.
        "summary_note": sec.get("summary_note"),
        "not_covered": list(sec.get("not_covered", [])),
        "blocks": blocks,
    }


def section_title(slug: str, report_type: str = WEEKLY) -> str:
    spec = spec_for(report_type, slug)
    return spec.title if spec else slug


def serialize_review(review: CoordinatorReview) -> dict[str, Any]:
    items = review.review_items
    counts = {}
    for status in _STATUSES:
        group = [i for i in items if i.status == status]
        counts[status] = {
            "total": len(group),
            "unresolved": sum(1 for i in group if i.resolution is None),
            "fix_needed": sum(1 for i in group if i.resolution == FIX_NEEDED),
        }
    resolved = sum(1 for i in items if i.resolution is not None)
    dev = is_dev_draft(review)
    slug = section_slug(review)
    return _json_safe({
        "section_slug": slug,
        "section_title": section_title(slug, review.report_type),
        "report_type": review.report_type,
        "report_title": TYPES[review.report_type].title,
        "period": review.period,
        "run_id": review.run_id,
        "decision": review.decision,
        "decided_at": review.decided_at,
        "locked": review.decision is not None,
        "is_approvable": review.is_approvable,
        "is_dev_draft": dev,
        "dev_mode_label": DEV_MODE_LABEL if dev else None,
        "progress": {
            "total": len(items),
            "resolved": resolved,
            "unresolved": len(items) - resolved,
            "fix_needed": sum(1 for i in items if i.resolution == FIX_NEEDED),
        },
        "counts": counts,
        # The weekly Digital Payments content has its own shape; every other section, the
        # Markets Reviews' Digital Payments included, is made of blocks.
        "section": _serialize_blocks(review) if "blocks" in review.section else _serialize_section(review),
        "review_items": [{"index": n, **item.to_dict()} for n, item in enumerate(items)],
    })
