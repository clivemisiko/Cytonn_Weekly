from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from cytonn_weekly.notable import store as notable_store
from cytonn_weekly.notable.registry import DetectorContext, run_detectors
from cytonn_weekly.notable.suggestion import MAX_HEADLINE
from cytonn_weekly.report_sections import spec_for
from cytonn_weekly.report_types import WEEKLY
from cytonn_weekly.weekly.week import Week
from api.deps import Deps, week_of
from api.schemas import NotableDecision, ReportType


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    def notable_section(slug: str) -> None:
        if spec_for(WEEKLY, slug) is None:
            raise HTTPException(404, f"no section {slug!r} in the weekly report")

    def notable_state(slug: str, week: Optional[Week]) -> dict:
        """The section's suggestions for the week, each with the analyst's decision on it (or null)."""
        if week is None:  # a report that is not the weekly one: nothing is computed for it yet
            return {"section": slug, "week_ending": None, "suggestions": [], "failed_checks": 0}
        found, failed = run_detectors(d.detectors, slug, DetectorContext(week.ending))
        decided = notable_store.load(d.db_path, week.ending.isoformat(), slug)
        return {"section": slug, "week_ending": week.ending.isoformat(), "failed_checks": failed,
                "suggestions": [{**s.to_dict(), "decision": decided.get(s.id)} for s in found]}

    @router.get("/api/notable/{section}")
    def notable_get(section: str, week_ending: Optional[str] = Query(default=None, max_length=10),
                    report_type: ReportType = Query(default=WEEKLY)) -> dict:
        """The suggestions for one section of one week, highest rank first.  Only the weekly report has any, for now."""
        notable_section(section)
        if report_type != WEEKLY:
            return notable_state(section, None)
        if week_ending is None:
            raise HTTPException(422, "the weekly report's suggestions need week_ending, the Friday the week ends on (2026-10-02)")
        return notable_state(section, week_of(week_ending))

    @router.post("/api/notable/{section}/decisions")
    def notable_decide(section: str, body: NotableDecision, week_ending: str = Query(max_length=10)) -> dict:
        """Select (accept, or edit and select) or dismiss a suggestion.  404 for an id the section does not have this week."""
        notable_section(section)
        week = week_of(week_ending)
        edited = body.edited_headline
        if edited is not None:
            edited = " ".join(edited.split())
            if body.decision != "selected":
                raise HTTPException(422, "only a selected suggestion can carry a reworded headline")
            if not edited:
                raise HTTPException(422, "the headline cannot be empty")
            if len(edited) > MAX_HEADLINE:
                raise HTTPException(422, f"the headline can be at most {MAX_HEADLINE} characters")
        if body.dismiss_reason is not None and body.decision != "dismissed":
            raise HTTPException(422, "only a dismissed suggestion can carry a reason")
        # ponytail: the detectors run again on every write; cache per request if one ever reads heavy history.
        current = next((s for s in notable_state(section, week)["suggestions"] if s["id"] == body.suggestion_id), None)
        if current is None:
            raise HTTPException(404, f"no suggestion {body.suggestion_id!r} for {section} in the week ending {week.ending.isoformat()}")
        notable_store.save(d.db_path, week.ending.isoformat(), section, body.suggestion_id, body.decision,
                           None if edited == current["headline"] else edited, body.dismiss_reason)
        return notable_state(section, week)

    @router.delete("/api/notable/{section}/decisions/{suggestion_id}")
    def notable_restore(section: str, suggestion_id: str, week_ending: str = Query(max_length=10)) -> dict:
        """Take the decision back: the suggestion is open again.  404 if there was none."""
        notable_section(section)
        week = week_of(week_ending)
        if not notable_store.delete(d.db_path, week.ending.isoformat(), section, suggestion_id):
            raise HTTPException(404, f"no saved decision for suggestion {suggestion_id!r} in the week ending {week.ending.isoformat()}")
        return notable_state(section, week)

    return router
