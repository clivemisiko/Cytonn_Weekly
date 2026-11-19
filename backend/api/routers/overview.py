import logging
from datetime import date, datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from cytonn_weekly.equities import companies as company_list
from cytonn_weekly.report_sections import companion_kinds, is_current, is_this_week, latest_runs, sections_for
from cytonn_weekly.report_types import REPORT_TYPES, TYPES, WEEKLY, suggested_period, week_ending_of
from cytonn_weekly.weekly.week import latest_friday
from api.runs import FAILED, Run
from api.serialize import DEV_MODE_LABEL, serialize_review
from api.deps import Deps, chosen_report, configured_provider, provider_label, provider_problem, uses_provider, PROVIDERS
from api.schemas import ReportType

log = logging.getLogger(__name__)


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @router.get("/api/config")
    def config() -> dict:
        """What the start screen needs before any review exists: who would draft, and at what cost."""
        provider = configured_provider()
        return {
            "provider": provider_label(),
            "provider_valid": provider in PROVIDERS,
            "dev_mode": provider == "local",
            "dev_mode_label": DEV_MODE_LABEL,
            "spends_api_budget": provider == "bedrock",
            "provider_problem": provider_problem(),
        }


    def report_types() -> list[dict]:
        today = date.today()
        return [{"slug": t, "title": TYPES[t].title, "published_as": TYPES[t].published_as,
                 "period_hint": TYPES[t].period_hint, "period_required": TYPES[t].period_required,
                 "suggested_period": suggested_period(t, today)} for t in REPORT_TYPES]


    @router.get("/api/report-types")
    def list_report_types() -> dict:
        return {"report_types": report_types(), "companion_kinds": companion_kinds()}


    @router.get("/api/equities/companies")
    def equities_companies() -> dict:
        """The listed banks and insurers the weekly Equities part covers, and whether each one's website is set."""
        try:
            return {"companies": company_list.status(), "searches": company_list.SEARCHES_PER_COMPANY,
                    "pages": company_list.PAGES_PER_COMPANY}
        except (OSError, ValueError) as exc:
            log.warning("companies.json could not be read: %s", type(exc).__name__)
            raise HTTPException(500, "The list of banks and insurers (equities/companies.json) cannot be read. Check the file.")


    @router.get("/api/sections")
    def overview(
        report_type: ReportType = Query(default=WEEKLY),
        period: Optional[str] = Query(default=None, max_length=40),
        kind: Optional[str] = Query(default=None, max_length=40),
    ) -> dict:
        """One report's sections at a glance: whether each can be drafted, and its review for this period, if any.

        With no arguments this is the weekly report with no period label, exactly what it
        showed before report types existed.  A Markets Review needs its period (422
        without one); a companion report lists its sections once a kind is given.
        """
        period, kind = chosen_report(report_type, period, kind)
        newest = latest_runs(d.db_path, report_type, period)
        today = date.today()
        out = []
        for spec in sections_for(report_type, kind):
            latest = None
            run = newest.get(spec.slug)
            if run is not None:
                review = d.load(run["run_id"])
                s = serialize_review(review)
                latest = {
                    "run_id": run["run_id"], "run_date": run["run_date"], "this_week": is_this_week(run["run_date"], today),
                    "current": is_current(report_type, period, run["run_date"], today),
                    "decision": s["decision"], "decided_at": s["decided_at"], "progress": s["progress"],
                    "counts": s["counts"], "is_dev_draft": s["is_dev_draft"],
                    "week_start": s["section"].get("week_start"), "week_end": s["section"].get("week_end"),
                    "topic": s["section"].get("topic"),
                }
            out.append({
                "slug": spec.slug, "title": spec.title, "available": spec.available, "needs_topic": spec.needs_topic,
                "requires_approved": spec.requires_approved,
                "uses_provider": uses_provider(spec),
                "reason": spec.reason or None, "unblock": spec.unblock or None, "built_parts": list(spec.built_parts),
                "subsections": list(spec.subsections), "charts": list(spec.charts),
                "steps": [{"title": t, "body": b} for t, b in spec.steps], "latest": latest,
            })
        week = week_ending_of(period) if report_type == WEEKLY else None
        report = {"type": report_type, "title": TYPES[report_type].title, "period": period, "kind": kind,
                  "published_as": TYPES[report_type].published_as,
                  # The weekly report's week: the Friday its period names, and the Friday to suggest.
                  "week_ending": week.isoformat() if week else None,
                  "suggested_week_ending": latest_friday(today).isoformat()}
        # The drafts holding a seat and those queued, across every section and report: a draft is not saved until it
        # finishes, so without this the overview could not show it at all.  ``drafting`` (the longest-held seat alone) is
        # the older single key, kept for one release.
        drafting = d.draft_slot.status()
        if drafting:  # lets the screen link to the running draft's page; None for a draft the synchronous route runs
            drafting["run_id"] = d.runs.running_id(drafting["report_type"], drafting["period"], drafting["slug"])
        return {"today": today.isoformat(), "drafting": drafting, "drafting_list": drafting_list(), "report": report,
                "report_types": report_types(), "companion_kinds": companion_kinds(), "sections": out}


    def drafting_list() -> list[dict]:
        """Every draft holding a seat (running) and every queued run: section, run id, state, position, start time and,
        for a running one, its latest step (the last event it reported)."""
        def step(run: Optional[Run]) -> Optional[dict]:
            last = run.events[-1] if run and run.events else None
            return {"kind": last.kind, "label": last.label, "detail": last.detail} if last else None

        out = []
        for h in d.draft_slot.statuses():
            run_id = d.runs.running_id(h["report_type"], h["period"], h["slug"])
            out.append({"section": h["slug"], "title": h["title"], "report_type": h["report_type"], "period": h["period"],
                        "run_id": run_id, "state": "running", "position": None, "started_at": h["started_at"],
                        "elapsed_seconds": h["elapsed_seconds"], "stale": h["stale"],
                        "stale_after_seconds": h["stale_after_seconds"], "step": step(d.runs.get(run_id) if run_id else None)})
        with d.seats:
            queued = [r for r, _, _ in d.waiting]
        for i, r in enumerate(queued):
            out.append({"section": r.section, "title": r.section_title, "report_type": r.report_type, "period": r.period,
                        "run_id": r.run_id, "state": "queued", "position": i + 1,
                        "started_at": datetime.fromtimestamp(r.started_at, tz=timezone.utc).isoformat(timespec="seconds"),
                        "elapsed_seconds": max(0, int(d.clock() - r.started_at)), "stale": False,
                        "stale_after_seconds": int(d.draft_stale_after), "step": None})
        # A section whose newest run failed keeps showing why until it is drafted again (in memory, like the runs).
        for r in d.runs.latest_by_key():
            if r.status == FAILED:
                reason = r.events[-1].detail if r.events else None
                out.append({"section": r.section, "title": r.section_title, "report_type": r.report_type, "period": r.period,
                            "run_id": r.run_id, "state": "failed", "position": None, "reason": reason,
                            "started_at": datetime.fromtimestamp(r.started_at, tz=timezone.utc).isoformat(timespec="seconds"),
                            "elapsed_seconds": 0, "stale": False, "stale_after_seconds": int(d.draft_stale_after), "step": None})
        return out

    return router
