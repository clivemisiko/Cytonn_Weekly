"""Section content and coordinator review for every section after Digital Payments.

Reuses the Digital Payments review model as-is: ``ReviewItem`` and
``CoordinatorReview`` (coordinator_review.py) were already section-agnostic, and
review_store.py already takes a ``section`` slug.  Only ``build_coordinator_review``
there is Digital-Payments-shaped (stock table, outlook stats, highlights), so this
module is its counterpart for a section made of generic blocks.

Section content (what ``CoordinatorReview.section`` holds, stored once and never
rewritten)::

    {
      "section": "equities",          # slug; the API dispatches on it (Digital Payments has none)
      "title": "Equities",
      "week_start": "2026-09-26", "week_end": "2026-10-02",
      "blocks": [...],                 # in report order
      "pieces_found": 3, "pieces_expected": 4, "shortfall": 1,
      "warnings": [...],
    }

Block kinds:

* ``table``       -- {id, numeral, title, columns: [{key, label, fmt, decimals}], key_field,
                     label_field, rows (display strings), source_rows (raw), source: {name, url, as_of}}.
                     Unlike Digital Payments, display rows are stored beside the raw rows, so the
                     screen never needs a section-specific formatter.
* ``narrative``   -- one drafted piece: {id, numeral, headline, body_md, body, claims, links,
                     warnings, drafted_by, search_scope, topic}.
* ``unavailable`` -- a part of the real report this tool cannot draft yet: {id, numeral, title,
                     reason, unblock}.  It still becomes a review item, so a section cannot be
                     approved without the coordinator explicitly acknowledging what is missing.
* ``supplied``    -- text the coordinator typed in, carried verbatim and never drafted or checked
                     (Company Updates, Cytonn's own promotional copy): {id, numeral, title, body_md,
                     supplied_by}.  It is one review item, never marked verified.
* ``computed``    -- a paragraph the tool worked out from published figures (common/computed.py):
                     {id, numeral, title, body_md, figures, sources, notes}.  One review item per
                     figure: clean when it is made only of published inputs and equals what the
                     checker works out again; not auto-verified when it rests on a typed workbook
                     cell; flagged on any mismatch, an unconfirmed OCR reading or disagreeing sources.
* ``carried``     -- text copied from the previous issue (common/computed.py): {id, numeral, title,
                     body_md, carried_from}.  Always one flagged item, "carried forward, edit
                     before approving".

A table block may also say where its rows came from.  ``row_origin: "analyst_input"`` with an
``origin_note`` (or ``_origin`` / ``_note`` on one source row) makes a row that passes its
exact-match not auto-verified instead of clean: the figures match their source, but the source is
a cell someone typed.  ``second_sources`` (``[{row, column, source, value}]``) are independent
second readings handed to the table check, which flags any that disagree.

The quarterly, half-year and annual reviews (periodic/) add, at the top level,
``report_type``, ``period``, ``period_start``/``period_end`` and ``chart_notes``: the real
issue's chart titles for that section, which the tool does not generate and the
coordinator adds by hand.

Statuses keep their Digital Payments meaning: ``flagged`` (a checker flag), ``clean``
(checked, no flag), ``not_auto_verified`` (a drafted claim: its figures may have been
matched against the cited span, but its wording never is).
"""

from __future__ import annotations

from typing import Any, Optional

from cytonn_weekly.checkers.digital_payments import NOT_IMPLEMENTED, UNSOURCED, CheckReport, Flag
from cytonn_weekly.checkers.digital_payments import SourceValue
from cytonn_weekly.common.checks import (
    CLAIM_SCOPE,
    TABLE_SCOPE,
    UNAVAILABLE_SCOPE,
    check_claim,
    check_table_block,
    row_subject,
)
from cytonn_weekly.common.computed import (
    ANALYST,
    CARRIED_SCOPE,
    COMPUTED_SCOPE,
    carried_flag,
    check_figure_record,
    figure_subject,
)
from cytonn_weekly.common.formatting import format_rows
from cytonn_weekly.common.run_events import CHECK_FINISHED, CHECK_STARTED, Observer, emit
from cytonn_weekly.digital_payments.coordinator_review import (
    CLEAN,
    FLAGGED,
    NOT_AUTO_VERIFIED,
    TABLE_ROW,
    CoordinatorReview,
    ReviewItem,
)

# ReviewItem.kind values added by this module (TABLE_ROW is reused).
CLAIM = "claim"
UNAVAILABLE_PART = "unavailable_part"
SUPPLIED_TEXT = "supplied_text"
COMPUTED_FIGURE = "computed_figure"
CARRIED_TEXT = "carried_text"

ANALYST_ROW_NOTE = ("Not auto-verified: this row's figures match their source exactly, but the source is typed by "
                    "an analyst, not published. Check it against the workbook before accepting.")

SUPPLIED_NOTE = (
    "Supplied by you and carried verbatim. The tool neither drafts nor checks this text, so read it "
    "before accepting."
)

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV",
         "XVI", "XVII", "XVIII", "XIX", "XX", "XXI", "XXII", "XXIII", "XXIV", "XXV"]
_REF_CHARS = 80


def numbered(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every block its roman numeral in order (the report numbers its sub-items)."""
    return [{**b, "numeral": ROMAN[i]} for i, b in enumerate(blocks)]


def table_block(block_id: str, title: str, columns: list[dict[str, Any]], source_rows: list[dict[str, Any]],
                key_field: str, label_field: str, source: dict[str, Any]) -> dict[str, Any]:
    """A table block: the raw source rows and their display-formatted rows, matched on ``key_field``."""
    return {
        "kind": "table", "id": block_id, "title": title, "columns": columns, "key_field": key_field,
        "label_field": label_field, "rows": format_rows(source_rows, columns, keep=(key_field,)),
        "source_rows": source_rows, "source": source,
    }


def unavailable_block(block_id: str, title: str, reason: str, unblock: str) -> dict[str, Any]:
    return {"kind": "unavailable", "id": block_id, "title": title, "reason": reason, "unblock": unblock}


def narrative_block(block_id: str, piece: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "narrative", "id": block_id, **piece}


def supplied_block(block_id: str, title: str, text: str) -> dict[str, Any]:
    return {"kind": "supplied", "id": block_id, "title": title, "body_md": text, "supplied_by": "coordinator"}


def second_sources(block: dict[str, Any]) -> dict[tuple[str, str], list[SourceValue]]:
    """A table block's ``second_sources`` as check_table_block takes them."""
    out: dict[tuple[str, str], list[SourceValue]] = {}
    for s in block.get("second_sources") or []:
        out.setdefault((row_subject(block["id"], s["row"]), s["column"]), []).append(SourceValue(s["source"], s["value"]))
    return out


def row_origin(block: dict[str, Any], src: dict[str, Any]) -> tuple[Optional[str], str]:
    """(origin, note) of one table row: its own ``_origin`` / ``_note``, else the block's."""
    origin = src.get("_origin") or block.get("row_origin")
    return origin, (src.get("_note") or block.get("origin_note") or ANALYST_ROW_NOTE)


def check_section(content: dict[str, Any], on_event: Optional[Observer] = None) -> CheckReport:
    """Every check this section supports: table exact-match, claim figures, and a flag per missing part.

    ``on_event`` (common/run_events.py) is told as each table's and each drafted piece's check
    starts and ends, with the number of review items build_review() will make of it per status
    (a table row is clean or flagged; a claim is flagged or, at best, not auto-verified).  It
    changes nothing in the report.
    """
    report = CheckReport()
    for b in content.get("blocks", []):
        if b["kind"] == "table":
            emit(on_event, CHECK_STARTED, b["title"])
            part = check_table_block(b, second_sources(b))
            report.flags.extend(part.flags)
            report.checked += part.checked
            key = b["key_field"]
            rows = {r[key] for r in b.get("source_rows", [])} | {r[key] for r in b.get("rows", [])}
            flagged = {f.subject for f in part.flags}
            flagged_rows = sum(1 for k in rows if row_subject(b["id"], k) in flagged)
            typed = sum(1 for r in b.get("source_rows", []) if row_origin(b, r)[0] == ANALYST
                        and row_subject(b["id"], r[key]) not in flagged)
            counts = {"clean": len(rows) - flagged_rows - typed, "flagged": flagged_rows}
            if typed:
                counts["not_auto_verified"] = typed
            emit(on_event, CHECK_FINISHED, b["title"], counts=counts)
        elif b["kind"] == "computed":
            emit(on_event, CHECK_STARTED, b["title"])
            counts = {"clean": 0, "flagged": 0, "not_auto_verified": 0}
            for fig in b.get("figures", []):
                flags, note = check_figure_record(b, fig)
                report.flags.extend(flags)
                report.checked += 1
                counts["flagged" if flags else "not_auto_verified" if note else "clean"] += 1
            emit(on_event, CHECK_FINISHED, b["title"], counts=counts)
        elif b["kind"] == "carried":
            report.flags.append(carried_flag(b))
        elif b["kind"] == "narrative":
            emit(on_event, CHECK_STARTED, b.get("headline", ""))
            claims = b.get("claims") or []
            flagged_claims = 0
            for n, claim in enumerate(claims):
                flags = check_claim(b["id"], n, claim).flags
                report.flags.extend(flags)
                flagged_claims += bool(flags)
            # A piece with no cited claim at all becomes one flagged item (build_review).
            emit(on_event, CHECK_FINISHED, b.get("headline", ""),
                 counts={"flagged": flagged_claims if claims else 1, "not_auto_verified": len(claims) - flagged_claims})
        elif b["kind"] == "unavailable":
            report.flags.append(Flag(
                kind=NOT_IMPLEMENTED, scope=UNAVAILABLE_SCOPE, subject=b["id"], field=None,
                message=(f"{b['title']} is not drafted by the tool. Accept to publish the section without it, "
                         "or mark fix needed to hold the section until it is supplied"),
            ))
    return report


def _short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= _REF_CHARS else text[: _REF_CHARS - 1].rstrip() + "…"


def _claim_context(claim: dict[str, Any]) -> dict[str, Any]:
    return {k: claim.get(k, "") for k in ("text", "url", "title", "cited_text")}


def build_review(content: dict[str, Any], report: CheckReport) -> CoordinatorReview:
    """One ReviewItem per table row, per drafted claim, and per unavailable part.

    As in Digital Payments, "clean" is derived (a checked row no flag points at)
    and every flag lands on some item, so none can go missing.  Raises ValueError
    if the section has table figures but the report compared none of them.
    """
    by_subject: dict[tuple[str, str], list[Flag]] = {}
    for f in report.flags:
        if f.scope not in (TABLE_SCOPE, CLAIM_SCOPE, UNAVAILABLE_SCOPE, COMPUTED_SCOPE, CARRIED_SCOPE):
            raise ValueError(f"flag with unrecognised scope {f.scope!r}: {f.message}")
        by_subject.setdefault((f.scope, f.subject), []).append(f)

    blocks = content.get("blocks", [])
    has_figures = any(b["kind"] == "table" and b.get("source_rows") for b in blocks)
    if has_figures and report.checked == 0 and not any(s == TABLE_SCOPE for s, _ in by_subject):
        raise ValueError("check report compared no table figures; run check_section() on this content first")

    used: set[tuple[str, str]] = set()
    items: list[ReviewItem] = []
    for b in blocks:
        if b["kind"] == "table":
            label = b.get("label_field") or b["key_field"]
            keys = [r[b["key_field"]] for r in b.get("source_rows", [])]
            keys += [r[b["key_field"]] for r in b.get("rows", []) if r[b["key_field"]] not in keys]
            for k in keys:
                subject = (TABLE_SCOPE, row_subject(b["id"], k))
                used.add(subject)
                src = next((r for r in b.get("source_rows", []) if r[b["key_field"]] == k), {})
                name = src.get(label) or k
                ref = f"{b['title']}: {name}"
                flags = by_subject.get(subject, [])
                origin, note = row_origin(b, src)
                if flags:
                    items.append(ReviewItem(kind=TABLE_ROW, ref=ref, status=FLAGGED, detail=flags))
                elif origin == ANALYST:
                    items.append(ReviewItem(kind=TABLE_ROW, ref=ref, status=NOT_AUTO_VERIFIED, detail=note))
                else:
                    items.append(ReviewItem(kind=TABLE_ROW, ref=ref, status=CLEAN, detail=None))
        elif b["kind"] == "computed":
            for fig in b.get("figures", []):
                subject = (COMPUTED_SCOPE, figure_subject(b["id"], fig["key"]))
                used.add(subject)
                ref = f"{b['title']}: {fig['label']} ({fig.get('display', '')})"
                flags = by_subject.get(subject, [])
                context = {"text": b.get("body_md", ""), "inputs": fig.get("inputs", {}), "note": fig.get("note", "")}
                if flags:
                    items.append(ReviewItem(kind=COMPUTED_FIGURE, ref=ref, status=FLAGGED, detail=flags, context=context))
                    continue
                note = check_figure_record(b, fig)[1]
                items.append(ReviewItem(kind=COMPUTED_FIGURE, ref=ref, status=NOT_AUTO_VERIFIED if note else CLEAN,
                                        detail=note or None, context=context))
        elif b["kind"] == "carried":
            subject = (CARRIED_SCOPE, b["id"])
            used.add(subject)
            items.append(ReviewItem(kind=CARRIED_TEXT, ref=f"{b['title']} (carried forward)", status=FLAGGED,
                                    detail=by_subject.get(subject) or [carried_flag(b)],
                                    context={"text": b.get("body_md", "")}))
        elif b["kind"] == "narrative":
            for n, claim in enumerate(b.get("claims") or []):
                subject = (CLAIM_SCOPE, f"{b['id']}#{n}")
                used.add(subject)
                ref = f"{b.get('numeral', '')} {b.get('headline', '')}: {_short(claim.get('text', ''))}".strip()
                flags = by_subject.get(subject, [])
                if flags:
                    items.append(ReviewItem(kind=CLAIM, ref=ref, status=FLAGGED, detail=flags,
                                            context=_claim_context(claim)))
                else:
                    items.append(ReviewItem(kind=CLAIM, ref=ref, status=NOT_AUTO_VERIFIED,
                                            detail=check_claim(b["id"], n, claim).note,
                                            context=_claim_context(claim)))
            if not b.get("claims"):
                # A drafted piece with no cited claim at all still needs a human look.
                items.append(ReviewItem(
                    kind=CLAIM, ref=f"{b.get('numeral', '')} {b.get('headline', '')}".strip(), status=FLAGGED,
                    detail=[Flag(kind=UNSOURCED, scope=CLAIM_SCOPE, subject=b["id"], field=None,
                                 message="this drafted piece records no cited claim; nothing in it traces to a source")],
                ))
        elif b["kind"] == "supplied":
            items.append(ReviewItem(kind=SUPPLIED_TEXT, ref=f"{b['title']} (supplied by you)",
                                    status=NOT_AUTO_VERIFIED, detail=SUPPLIED_NOTE,
                                    context={"text": b.get("body_md", "")}))
        elif b["kind"] == "unavailable":
            subject = (UNAVAILABLE_SCOPE, b["id"])
            used.add(subject)
            items.append(ReviewItem(
                kind=UNAVAILABLE_PART, ref=f"{b['title']} (not available yet)", status=FLAGGED,
                detail=by_subject.get(subject) or None,
                context={"text": f"{b['reason']} Unblocked by: {b['unblock']}"},
            ))
    for subject, flags in by_subject.items():
        if subject not in used:
            items.append(ReviewItem(kind=TABLE_ROW if subject[0] == TABLE_SCOPE else CLAIM,
                                    ref=subject[1], status=FLAGGED, detail=flags))
    return CoordinatorReview(section=content, review_items=items)
