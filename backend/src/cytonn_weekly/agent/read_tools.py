from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from cytonn_weekly import report_sections, source_pieces
from cytonn_weekly.agent.tools import LONG, Params, Refused, Tool, ToolContext
from cytonn_weekly.agent import readiness
from cytonn_weekly.common import source_policy
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.history import reads as history_reads
from cytonn_weekly.history import store as history_store
from cytonn_weekly.history import weekly as history_weekly
from cytonn_weekly.history.importer import CATALOG
from cytonn_weekly.real_estate import snips as snip_store
from cytonn_weekly.report_types import WEEKLY, week_ending_of
from cytonn_weekly.review import store as review_store
from cytonn_weekly.run_store import ACTIVE, INTERRUPTED, RunStore
from cytonn_weekly.weekly import analyst as weekly_analyst
from cytonn_weekly.weekly import export as weekly_export
from cytonn_weekly.weekly import inputs as weekly_inputs
from cytonn_weekly.weekly.week import Week

# Read tools for the analyst chat.  Each wraps a function the app already has, returns plain data, and names in its shape what the
# model may see.  None returns source text, a workbook cell, a snip's transcription, an analyst's note or an uploaded file's name.
# Tool names use underscores: the Messages API refuses dots.


def _week(ctx: ToolContext) -> Week:
    friday = week_ending_of(ctx.job["period"])
    if friday is None:
        raise Refused("This conversation is not about one week, so there is no week to look at.")
    return Week(friday)


class NoParams(Params):
    pass


# --- inputs.list, inputs.explain -------------------------------------------------------------

_FILE = ("read_date", "matches", "note", "received_at", "fetched_from")
_SLOT = {"slug": None, "title": None, "optional": None, "per_day": None, "fetchable": None, "received": None, "complete": None,
         "file": _FILE, "days": ("date", "weekday", "received")}
SLOT_SLUGS = tuple(weekly_inputs.BY_SLUG)


class InputsList(NoParams):
    pass


def inputs_list(args: InputsList, ctx: ToolContext) -> dict[str, Any]:
    return weekly_inputs.status(_week(ctx), ctx.root)


class InputsExplain(Params):
    slot: Literal[SLOT_SLUGS]   # type: ignore[valid-type]


def inputs_explain(args: InputsExplain, ctx: ToolContext) -> dict[str, Any]:
    slot = weekly_inputs.BY_SLUG[args.slot]
    got = next(s for s in weekly_inputs.status(_week(ctx), ctx.root)["slots"] if s["slug"] == args.slot)
    return {**got, "kind": slot.kind, "help": slot.help}


# --- form.get --------------------------------------------------------------------------------

FORM_SECTIONS = tuple(weekly_analyst.WORKBOOKS)


class FormGet(Params):
    section: Optional[Literal[FORM_SECTIONS]] = None   # type: ignore[valid-type]


def _form_item(item: dict[str, Any]) -> dict[str, Any]:
    """One form item without free text: numbers and dates as typed, but text and names only as present or not, and a workbook that
    could not be read as a flag, so nothing a person or a workbook wrote reaches the model as words."""
    base = {"key": item["key"], "label": item["label"], "type": item["type"], "source": item["source"], "used_in": item["used_in"],
            "carried": bool(item["carried"]), "needs_confirmation": item["needs_confirmation"],
            "workbook_problem": bool(item["workbook_note"]), "workbook_other_week": bool(item.get("workbook_stale")),
            "workbook_first": bool(item.get("workbook_first")), "differs": bool(item["differences"]),
            "differences": len(item["differences"])}
    if item["type"] == "table":
        return {**base, "rows": len(item["rows"] or []), "workbook_rows": None if item["workbook_rows"] is None else len(item["workbook_rows"]),
                "warnings": len(item["warnings"])}
    plain = item["kind"] in (weekly_analyst.NUMBER, weekly_analyst.DATE)
    workbook = item["workbook"]
    return {**base, "unit": item["unit"], "suggestable": item["suggestable"],
            "has_value": item["value"] not in (None, ""), "value": item["value"] if plain else None,
            "has_workbook_value": workbook is not None, "workbook_value": workbook["value"] if plain and workbook else None}


def form_get(args: FormGet, ctx: ToolContext) -> dict[str, Any]:
    section = args.section or ctx.job["section"]
    if section not in FORM_SECTIONS:
        raise Refused("This section has no analyst form. The form is for Fixed Income and Equities.")
    got = weekly_analyst.status(_week(ctx), ctx.root, section)
    return {"week_ending": got["week_ending"], "workbooks": got["workbooks"], "unconfirmed": got["unconfirmed"], "can_carry": got["can_carry"],
            "groups": [{"title": g["title"], "items": [_form_item(i) for i in g["items"]]} for g in got["groups"]]}


# --- sources.list, sites.suggest, snips.list -------------------------------------------------

class SourcesList(Params):
    subject: Optional[str] = None


def sources_list(args: SourcesList, ctx: ToolContext) -> dict[str, Any]:
    week = _week(ctx)
    found = source_store.list_for(args.subject, week.ending, ctx.sources_dir) if args.subject else source_store.list_all(week.ending, ctx.sources_dir)
    rows = []
    for s in found:
        published = date.fromisoformat(s.published_date) if s.published_date else None
        rows.append({**{k: getattr(s, k) for k in ("subject", "host", "title", "published_date", "origin", "fetched_at", "flags", "chars")},
                     "in_week": None if published is None else week.monday <= published <= week.ending})
    return {"week_starts": week.monday.isoformat(), "week_ends": week.ending.isoformat(), "count": len(rows), "sources": rows}


class SitesSuggest(Params):
    piece: str


def sites_suggest(args: SitesSuggest, ctx: ToolContext) -> dict[str, Any]:
    section, report_type = ctx.job["section"], ctx.job["report_type"]
    spec = report_sections.spec_for(report_type, section)
    if report_type == WEEKLY and section == "real_estate":
        raise Refused("The weekly Real Estate section is written from the snips you upload, so no site is searched for it.")
    if spec is None or not spec.available or spec.requires_approved:   # the same test as api.deps.uses_provider
        raise Refused("This section is not written from sources, so there are no sites to suggest.")
    hosts = [{"host": h, "kind": source_policy.kind_for(section, args.piece, h)} for h in source_policy.search_hosts(section, args.piece)]
    return {"section": section, "piece": args.piece, "hosts": hosts}


def snips_list(args: NoParams, ctx: ToolContext) -> dict[str, Any]:
    items = snip_store.list_snips(_week(ctx).ending, ctx.snips_dir)
    return {"sectors": [{"sector": label, "uploaded": sum(1 for i in items if i["sector"] == sid),
                         "read": sum(1 for i in items if i["sector"] == sid and i.get("text") is not None),
                         "confirmed": sum(1 for i in items if i["sector"] == sid and i["confirmed"])}
                        for sid, label in snip_store.SECTORS]}


# --- week_status -------------------------------------------------------------------------------

def week_status(args: NoParams, ctx: ToolContext) -> dict[str, Any]:
    section = ctx.job["section"]
    if ctx.job["report_type"] != WEEKLY or report_sections.spec_for(WEEKLY, section) is None:
        raise Refused("There is no weekly readiness check for this conversation.")
    week = _week(ctx)
    form = weekly_analyst.status(week, ctx.root, section) if section in FORM_SECTIONS else None
    got = readiness.classify(section, weekly_inputs.status(week, ctx.root), form)
    # Real Estate and Focus have parts the two functions above do not cover: counts only, no verdict (nothing says what is enough).
    if section == "real_estate":
        got["snips"] = snips_list(args, ctx)["sectors"]
    if section in ("real_estate", "focus"):
        found = sources_list(SourcesList(), ctx)["sources"]
        got["sources"] = {"total": len(found), "in_week": sum(1 for s in found if s["in_week"]),
                          "outside_week": sum(1 for s in found if s["in_week"] is False)}
        got["note"] = "The snip and source counts are as they are: this check does not say whether they are enough."
    if form is not None:   # where a carried or suggested figure came from, when the store holds it (nothing with CYTONN_HISTORY_READS off)
        lines = history_reads.source_lines(week, ctx.db_path)
        for entry in got["groups"]["carried_or_suggested"]:
            if entry["key"] in lines:
                entry["source"] = lines[entry["key"]]
    return got


# --- history_status, history_working ------------------------------------------------------------

def history_status(args: NoParams, ctx: ToolContext) -> dict[str, Any]:
    section, week = ctx.job["section"], _week(ctx)
    keys = [k for k, spec in CATALOG.items() if spec[2] == section]
    if ctx.job["report_type"] != WEEKLY or not keys:
        raise Refused("The history store holds no series for this section.")
    rows = []
    for key in keys:
        points = history_store.current(ctx.db_path, key, None, confirmed_only=False, since=week.monday.isoformat(), through=week.ending.isoformat())
        sure, waiting = [p for p in points if p["confirmed_at"]], [p for p in points if not p["confirmed_at"]]
        rows.append({"series": key, "label": CATALOG[key][3], "state": "confirmed" if sure else "unconfirmed" if waiting else "none",
                     "confirmed": len(sure), "unconfirmed": len(waiting), "confirmed_dates": sorted({p["as_of"] for p in sure}),
                     "unconfirmed_dates": sorted({p["as_of"] for p in waiting}), "subjects": len({p["subject"] for p in points})})
    return {"section": section, "week_ending": week.ending.isoformat(), "setting": history_reads.mode(), "series": rows,
            "failed_store_writes": history_weekly.failed_writes(), "failed_store_reads": history_reads.counts["failed_reads"],
            "compare_differences": history_reads.counts["differences"]}


class HistoryWorking(Params):
    series: Literal[tuple(CATALOG)]   # type: ignore[valid-type]
    day: date


def history_working(args: HistoryWorking, ctx: ToolContext) -> dict[str, Any]:
    week = _week(ctx)
    if not week.monday <= args.day <= week.ending:
        raise Refused(f"Only dates in this report's week are available: {week.monday.isoformat()} to {week.ending.isoformat()}.")
    secret = args.series in history_reads.CONFIDENTIAL
    points = []
    for p in history_store.current(ctx.db_path, args.series, None, confirmed_only=False, since=args.day.isoformat(), through=args.day.isoformat()):
        row = {"origin": p["origin"], "source_kind": p["source_kind"], "confirmed": p["confirmed_at"] is not None}
        if p["source_kind"] != "working":
            row["source_ref"] = p["source_ref"]
        if not secret:   # a confidential series gives its provenance only: no value, no subject and no working
            row.update(subject=p["subject"], value=p["value"], unit=CATALOG[args.series][0])
            if p["source_kind"] == "working":
                row["working"] = p["source_ref"]
        points.append(row)
    return {"series": args.series, "day": args.day.isoformat(), "confidential": secret, "count": len(points), "points": points,
            "note": "This series' values and workings are not shown." if secret else None}


# --- draft.status, review.summary, review.explain, export.status -----------------------------

def draft_status(args: NoParams, ctx: ToolContext) -> dict[str, Any]:
    key = (ctx.job["report_type"], ctx.job["period"], ctx.job["section"])
    run = next((r for r in ctx.runs.latest_by_key() if r.key == key), None) if ctx.runs is not None else None
    if run is not None:
        got = run.to_dict()
        return {"state": got["status"], "source": "live", "review_id": got["review_id"], "is_dev_draft": got["is_dev_draft"],
                "events": got["events"][-12:]}
    stored = RunStore(ctx.db_path).latest_for(*key)   # after a restart, or once the registry has dropped an old run
    if stored is None:
        return {"state": "none"}
    row, events = stored
    return {"state": INTERRUPTED if row["status"] in ACTIVE else row["status"], "source": "saved_record",
            "note": "The live run is gone from memory; this is the record saved in the database.", "review_id": row["review_id"],
            "is_dev_draft": None if row["is_dev_draft"] is None else bool(row["is_dev_draft"]), "events": [e.to_dict() for e in events[-12:]]}


def _review(ctx: ToolContext):
    job = ctx.job
    latest = report_sections.latest_runs(ctx.db_path, job["report_type"], job["period"]).get(job["section"])
    if latest is None:
        raise Refused("No draft of this section has been saved for this week yet.")
    return review_store.load_review(latest["run_id"], db_path=ctx.db_path)


def review_summary(args: NoParams, ctx: ToolContext) -> dict[str, Any]:
    review = _review(ctx)
    counts = {s: len(review.by_status(s)) for s in ("flagged", "not_auto_verified", "clean")}
    return {"review_id": review.run_id, "decision": review.decision, "decided_at": review.decided_at, "counts": counts,
            "items": [{"index": n, "kind": i.kind, "ref": i.ref, "status": i.status, "resolution": i.resolution}
                      for n, i in enumerate(review.review_items) if i.status != "clean"]}


class ReviewExplain(Params):
    index: int


def review_explain(args: ReviewExplain, ctx: ToolContext) -> dict[str, Any]:
    review = _review(ctx)
    if not 0 <= args.index < len(review.review_items):
        raise Refused(f"This review has items 0 to {len(review.review_items) - 1}.")
    item = review.review_items[args.index]
    flags = item.detail if isinstance(item.detail, list) else []
    return {"index": args.index, "kind": item.kind, "ref": item.ref, "status": item.status, "resolution": item.resolution,
            "flags": [{"kind": f.kind, "scope": f.scope, "subject": f.subject, "field": f.field, "message": f.message, "drafted": f.drafted,
                       "expected": f.expected, "sources": f.sources} for f in flags],
            "note": item.detail if isinstance(item.detail, str) else None,
            "source": {"title": item.context.get("title"), "host": source_store.host_of(item.context.get("url") or "")} if item.context else None}


def export_status(args: NoParams, ctx: ToolContext) -> dict[str, Any]:
    if ctx.job["report_type"] != WEEKLY:
        raise Refused("Only the weekly report has an export.")
    return weekly_export.export_status(ctx.db_path, ctx.job["period"], inputs_root=ctx.root)


# --- the list ---------------------------------------------------------------------------------

_ENTRY = ("kind", "key", "label", "why")
_REVIEW_ITEM = ("index", "kind", "ref", "status", "resolution")
READ_TOOLS = [
    Tool("inputs_list", "List the week's uploaded files per input: received or not, the date read from each, whether it fits the week, "
         "and whether the tool fetched it.", InputsList, inputs_list,
         {"week_ending": None, "monday": None, "previous_friday": None, "holiday_note": None, "slots": _SLOT}),
    Tool("inputs_explain", "Explain one weekly input: what it is, whether it is optional, and what has been received for it.",
         InputsExplain, inputs_explain, {**_SLOT, "kind": None, "help": None}),
    Tool("form_get", "Show the weekly analyst inputs form for Fixed Income or Equities: each item, whether a value was typed, whether the "
         "workbook has one, and whether they differ. Text and table contents are not shown, only counts.", FormGet, form_get,
         {"week_ending": None, "workbooks": ("fixed_income", "equities"), "unconfirmed": ("key", "label"), "can_carry": None,
          "groups": {"title": None, "items": ("key", "label", "type", "source", "used_in", "carried", "needs_confirmation",
                                              "workbook_problem", "workbook_other_week", "workbook_first", "differs", "differences", "rows", "workbook_rows", "warnings", "unit",
                                              "suggestable", "has_value", "value", "has_workbook_value", "workbook_value")}}),
    Tool("sources_list", "List the saved sources for the week: host, title, published date, whether it falls inside Monday to Friday "
         "of the week, flags. Never the text.", SourcesList, sources_list,
         {"week_starts": None, "week_ends": None, "count": None,
          "sources": ("subject", "host", "title", "published_date", "origin", "fetched_at", "flags", "chars", "in_week")}),
    Tool("sites_suggest", "Suggest which websites may be searched for one piece of this section. Hosts only; nothing is read.",
         SitesSuggest, sites_suggest, {"section": None, "piece": None, "hosts": ("host", "kind")}),
    Tool("snips_list", "Count the week's Real Estate snips per sector: uploaded, read and confirmed.", NoParams, snips_list,
         {"sectors": ("sector", "uploaded", "read", "confirmed")}),
    Tool("week_status", "Say what this section still needs for the week: what is fetched, what is carried or suggested and not yet "
         "confirmed, what needs the analyst, what is optional, and what is in place. For Real Estate and Focus it also gives snip "
         "and source counts, with no verdict.", NoParams, week_status,
         {"section": None, "week_ending": None, "counts": readiness.GROUPS, "note": None,
          # an upload's kept files by the name the tool stored them under; the prepare page's route adds the analyst's own name
          # after this trim (api/routers/jobs.py named()), so the model never sees it
          "groups": dict.fromkeys(readiness.GROUPS, {**dict.fromkeys((*_ENTRY, "source", "other_week")), "why": LONG, "files": ("stored_name",)}),
          "snips": ("sector", "uploaded", "read", "confirmed"), "sources": ("total", "in_week", "outside_week")}),
    Tool("history_status", "Say, for this section and week, which history-store series have a confirmed point, only an unconfirmed one, or none, "
         "with counts and dates, and how many store writes failed and compare-mode differences were found. No values.", NoParams, history_status,
         {"section": None, "week_ending": None, "setting": None, "failed_store_writes": None, "failed_store_reads": None, "compare_differences": None,
          "series": ("series", "label", "state", "confirmed", "unconfirmed", "confirmed_dates", "unconfirmed_dates", "subjects")}),
    Tool("history_working", "Show where one history-store figure for one date of this week came from: its origin and source reference and, for a "
         "figure the tool worked out, the working. The market P/E, the fund table and the placements show their provenance only, never a value.",
         HistoryWorking, history_working,
         {"series": None, "day": None, "confidential": None, "count": None, "note": None,
          "points": {"origin": None, "source_kind": None, "confirmed": None, "source_ref": None, "subject": None, "value": None, "unit": None, "working": LONG}}),
    Tool("draft_status", "Say where this section's draft run is: its state and its latest steps. 'source' says whether it is the live "
         "run or a saved record.", NoParams, draft_status,
         {"state": None, "source": None, "note": None, "review_id": None, "is_dev_draft": None,
          "events": ("seq", "kind", "label", "detail", "at")}),
    Tool("review_summary", "Summarise this section's saved draft review: the counts by status and every item that is flagged or not "
         "automatically verified.", NoParams, review_summary,
         {"review_id": None, "decision": None, "decided_at": None, "counts": ("flagged", "not_auto_verified", "clean"), "items": _REVIEW_ITEM}),
    Tool("review_explain", "Explain one review item by its index: what was checked, what the draft says, what the source says.",
         ReviewExplain, review_explain,
         {**dict.fromkeys(_REVIEW_ITEM[1:]), "index": None, "note": None, "source": ("title", "host"),
          "flags": {**dict.fromkeys(("kind", "scope", "subject", "field", "message", "drafted", "expected")), "sources": ("source", "value")}}),
    Tool("export_status", "Say whether the weekly report can be exported: each section's state and the charts still missing.",
         NoParams, export_status,
         {"period": None, "ready": None, "is_dev_draft": None, "dev_sections": None, "can_send": None, "charts_missing": None,
          "sections": ("slug", "title", "state", "run_id", "flagged_accepted_on_approval")}),
]
