"""A chart in a section: its block (metadata only), its review items and its run events.

The block holds what the review needs and nothing to redraw from: the caption, the cells read,
the point count, the window, the newest date, the last value, the average, the SHA-256 of the
PNG and of the series file, drawn or not drawn, and every defect.  The series and the picture are
files (charts/store.py).  The checks are run when the block is made, while the series is in hand,
and kept on the block as flags, so ``check_section`` and ``build_review`` work from the block alone.

A drawn chart becomes five review items: the last plotted point against the figure the draft
quotes, the average line against the workbook's own AVERAGE cell and the quoted average, the
freshness of the newest point, the rows left out of the series, and where the history comes
from ("from the analyst workbook, not verified").  A chart that is not drawn becomes one flagged
item for its defects, and one for its freshness when that is what stopped it.  Nothing about a
chart is ever clean except a freshness or a row check that found nothing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable, Optional

from cytonn_weekly.charts.series import ChartSeries, average, check_quoted, compare_average, read_series, windowed
from cytonn_weekly.charts.specs import AVERAGE_FROM, SPECS, ChartSpec
from cytonn_weekly.charts.store import sha256
from cytonn_weekly.checkers.digital_payments import Flag
from cytonn_weekly.common.formatting import MULTIPLE, PCT, fmt_value
from cytonn_weekly.common.run_events import PART_SKIPPED, PIECE_FINISHED, PIECE_STARTED, Observer, emit, fetch_source
from cytonn_weekly.digital_payments.coordinator_review import CLEAN, FLAGGED, NOT_AUTO_VERIFIED
from cytonn_weekly.notable.suggestion import FIXED_LABELS
from cytonn_weekly.weekly.workbook import Workbook

CHART_SCOPE = "chart"             # Flag.scope of every chart flag
CHART_ITEM = "chart"              # ReviewItem.kind of every chart item
STALE_FLAG = "stale"              # the newest point is older than the chart allows
SERIES_DEFECT_FLAG = "series_defect"   # anything else wrong with the series or the AVERAGE cell

POINT, AVERAGE, FRESHNESS, DEFECTS, SOURCE = "point", "average", "freshness", "defects", "source"
PROVENANCE = FIXED_LABELS["analyst_workbook"]      # "from the analyst workbook, not verified"
NOT_COMPARED = "The chart is not drawn, so its last point and average were not compared with the draft."
_FRESHNESS_DEFECTS = ("stale", "future")
_STATED_DEFECTS = ("stated_missing", "stated_unreadable")


@dataclass(frozen=True)
class Part:
    """One review item of a chart: its key in the block's checks, what it says, and its status when nothing flags it."""

    key: str
    ref: str
    status: str
    note: Optional[str]


# ---------------------------------------------------------------------------
# Making the block
# ---------------------------------------------------------------------------

def _fmt(spec: ChartSpec, value: Any) -> str:
    return fmt_value(value, PCT if spec.unit == "pct" else MULTIPLE, spec.decimals)


def _plain(flag: Flag, subject: str) -> dict[str, Any]:
    """A flag as JSON-safe data under the chart item it belongs to (Decimals become text)."""
    return json.loads(json.dumps({**asdict(flag), "scope": CHART_SCOPE, "subject": subject}, default=str))


def _flag(kind: str, subject: str, message: str) -> dict[str, Any]:
    return _plain(Flag(kind=kind, scope=CHART_SCOPE, subject=subject, field=None, message=message), subject)


def series_file(series: ChartSeries, workbook: str) -> bytes:
    """Every point read, with its cell, and every defect: what the chart was drawn from."""
    return json.dumps({
        "chart_id": series.spec.id, "week_ending": series.week_ending.isoformat(), "workbook": workbook,
        "sheet": series.spec.sheet, "unit": series.spec.unit,
        "points": [[p.day.isoformat(), str(p.value), p.cell] for p in series.points],
        "defects": [asdict(d) for d in series.defects],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _alt(series: ChartSeries, avg: Any) -> str:
    from cytonn_weekly.charts.draw import alt_text   # matplotlib loads only when a chart is drawn
    return alt_text(series, avg)


def chart_block(series: ChartSeries, workbook: str, quoted: dict[str, Any], png: Optional[bytes],
                series_json: Optional[bytes]) -> dict[str, Any]:
    spec, bid = series.spec, f"chart_{series.spec.id}"
    subject = lambda key: f"{bid}#{key}"   # noqa: E731
    drawn = series.drawn and png is not None
    avg = average(series) if series.points else None
    shown = windowed(series)
    latest = series.latest
    rows = [p.row for p in series.points]

    checks: dict[str, list[dict[str, Any]]] = {POINT: [], AVERAGE: [], FRESHNESS: [], DEFECTS: []}
    for d in series.defects:
        if d.kind in _FRESHNESS_DEFECTS:
            checks[FRESHNESS].append(_flag(STALE_FLAG if d.kind == "stale" else SERIES_DEFECT_FLAG, subject(FRESHNESS), d.message))
        else:
            key = AVERAGE if drawn and d.kind in _STATED_DEFECTS else DEFECTS
            text = d.message + (" This stops the chart from being drawn." if d.blocking else "")
            checks[key].append(_flag(SERIES_DEFECT_FLAG, subject(key), text))
    note = None
    if drawn:
        for f in check_quoted(series, quoted):
            key = POINT if f.field.startswith("last point") else AVERAGE
            checks[key].append(_plain(f, subject(key)))
        comparison = compare_average(series)
        if comparison.flag is not None:
            checks[AVERAGE].append(_plain(comparison.flag, subject(AVERAGE)))
        note = comparison.note
    else:
        checks[DEFECTS].append(_flag(SERIES_DEFECT_FLAG, subject(DEFECTS), NOT_COMPARED))

    return {
        "kind": "chart", "id": bid, "chart_id": spec.id, "title": spec.title, "caption": spec.caption,
        "status": "drawn" if drawn else "not_drawn",
        "source": {"workbook": workbook, "sheet": spec.sheet, "provenance": PROVENANCE,
                   "cells": f"{series.col}{min(rows)}:{series.col}{max(rows)}" if rows else None},
        "points": len(series.points),
        "window": {"years": spec.window_years, "first": shown[0].day.isoformat(), "last": shown[-1].day.isoformat(),
                   "points": len(shown)} if shown else None,
        "newest_date": latest.day.isoformat() if latest else None,
        "last_value": {"display": _fmt(spec, latest.value), "value": str(latest.value), "cell": latest.cell} if latest else None,
        "average": {"display": _fmt(spec, avg.display), "value": str(avg.value), "count": avg.count, "first": avg.first.isoformat(),
                    "last": avg.last.isoformat(), "cells": avg.cells, "from": AVERAGE_FROM.isoformat(), "note": note} if avg else None,
        "stated": {"cell": series.stated.cell, "value": None if series.stated.value is None else str(series.stated.value),
                   "formula_range": series.stated.formula_range} if series.stated else None,
        "png_sha256": sha256(png) if drawn else None,
        "series_sha256": sha256(series_json) if drawn and series_json else None,
        "alt": _alt(series, avg) if drawn else None,
        "defects": [asdict(d) | {"cells": list(d.cells)} for d in series.defects],
        "checks": checks,
    }


def chart_blocks(book: Optional[Workbook], workbook: str, week_ending: date, quoted: dict[str, Any],
                 missing: tuple[str, str], on_event: Optional[Observer] = None,
                 specs: Iterable[ChartSpec] = SPECS.values()) -> tuple[list[dict[str, Any]], dict[str, dict[str, bytes]]]:
    """Each chart's block, and the files of the drawn ones ({chart_id: {"png", "json"}}).

    With no workbook (``book`` None) each chart is an ``unavailable`` block saying why
    (``missing``: reason, what unblocks it).  ``quoted`` maps the section's figure keys to
    what its draft prints.
    """
    from cytonn_weekly.charts.draw import render_png      # matplotlib loads only when a chart is drawn
    from cytonn_weekly.common.review import unavailable_block   # common.review imports this module

    blocks: list[dict[str, Any]] = []
    files: dict[str, dict[str, bytes]] = {}
    for spec in specs:
        if book is None:
            blocks.append(unavailable_block(f"chart_{spec.id}", spec.title, *missing))
            continue
        emit(on_event, PIECE_STARTED, spec.title)
        series = fetch_source(on_event, f"{workbook}, '{spec.sheet}' ({spec.header})", read_series, book, spec, week_ending)
        png = render_png(series) if series.drawn else None
        series_json = series_file(series, workbook) if png else None
        blocks.append(chart_block(series, workbook, quoted, png, series_json))
        if png:
            files[spec.id] = {"png": png, "json": series_json}
            emit(on_event, PIECE_FINISHED, spec.title, detail="drawn")
        else:
            stop = next(d.message for d in series.defects if d.blocking)
            emit(on_event, PART_SKIPPED, spec.title, detail=f"Not drawn: {stop}")
    return blocks, files


# ---------------------------------------------------------------------------
# Reviewing it
# ---------------------------------------------------------------------------

def chart_parts(b: dict[str, Any]) -> list[Part]:
    """The chart's review items, in order, each with the status it has when no flag points at it."""
    title, checks = b["title"], b.get("checks") or {}
    if b["status"] != "drawn":
        parts = [Part(FRESHNESS, f"{title}: newest point", FLAGGED, None)] if checks.get(FRESHNESS) else []
        return parts + [Part(DEFECTS, f"{title}: not drawn", FLAGGED, None)]
    last, avg, src = b["last_value"], b["average"], b["source"]
    stated = b.get("stated") or {}
    average_note = (f"Worked out by the tool as the mean of {avg['cells']}, every point dated {avg['from']} or later "
                    f"({avg['count']} points), not only the {b['window']['years']} years shown. It prints the same figure as "
                    f"the workbook's AVERAGE cell {stated.get('cell', '')} and as the draft.")
    if avg.get("note"):
        average_note += " " + avg["note"]
    return [
        Part(POINT, f"{title}: last plotted point, {last['display']} on {b['newest_date']}", NOT_AUTO_VERIFIED,
             f"It equals the figure the draft quotes. Both rest on the analyst workbook ({src['sheet']}!{last['cell']}), "
             f"{PROVENANCE}."),
        Part(AVERAGE, f"{title}: average line, {avg['display']}", NOT_AUTO_VERIFIED, average_note),
        Part(FRESHNESS, f"{title}: newest point dated {b['newest_date']}", CLEAN, None),
        Part(DEFECTS, f"{title}: rows of the series", CLEAN, None),
        Part(SOURCE, f"{title}: where the plotted history comes from", NOT_AUTO_VERIFIED,
             f"From the analyst workbook, not verified: {src['workbook']}, '{src['sheet']}'!{src['cells']}. No second source "
             "checks the history; only the last point and the average are compared with the draft."),
    ]


def chart_flags(b: dict[str, Any]) -> list[Flag]:
    return [Flag(**f) for key in (POINT, AVERAGE, FRESHNESS, DEFECTS) for f in (b.get("checks") or {}).get(key, [])]


def chart_counts(b: dict[str, Any]) -> dict[str, int]:
    """Review items per status, as build_review will make them (for the check_finished event)."""
    flagged = {f.subject for f in chart_flags(b)}
    counts = {CLEAN: 0, FLAGGED: 0, NOT_AUTO_VERIFIED: 0}
    for p in chart_parts(b):
        counts[FLAGGED if f"{b['id']}#{p.key}" in flagged else p.status] += 1
    return counts
