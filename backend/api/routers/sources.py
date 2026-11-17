from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from cytonn_weekly.common import gather as source_gather
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.focus.review_run import clean_sections
from cytonn_weekly.report_sections import spec_for
from cytonn_weekly.source_pieces import pieces_for
from cytonn_weekly.report_types import TYPES, WEEKLY
from cytonn_weekly.weekly.week import latest_friday
from api.deps import Deps, chosen_report, uses_provider
from api.schemas import SourceBody, GatherBody, ReportType


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    def source_piece(section: str, subject: str, report_type: str, period: Optional[str], typed: Optional[str]):
        """(the section's spec, the normalized period, the piece) a source is for, or a plain refusal (404, 422)."""
        if section == "real_estate" and report_type == WEEKLY:
            raise HTTPException(422, "The weekly Real Estate section is written from the snips you upload, so nothing is searched "
                                     "or added here. Upload and confirm a snip instead.")
        period, _ = chosen_report(report_type, period, None)
        spec = spec_for(report_type, section)
        if spec is None:
            raise HTTPException(404, f"no section {section!r} in the {TYPES[report_type].title}")
        if not spec.available or not uses_provider(spec):
            raise HTTPException(422, f"{spec.title} is not written from sources, so there is nothing to supply for it.")
        try:
            titles = clean_sections(typed) if spec.needs_topic and typed and typed.strip() else []
            pieces = pieces_for(report_type, period, section, sections=titles or ([subject] if spec.needs_topic else []),
                                today=date.today())
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if pieces is None:
            raise HTTPException(422, f"{spec.title} has no pieces to supply sources for.")
        key = source_store.subject_key(subject)
        piece = next((p for p in pieces if source_store.subject_key(p.subject) == key), None)
        if piece is None:
            if spec.needs_topic:
                raise HTTPException(422, f"{subject!r} is not a section title you typed, or it is the closing part, which is "
                                         "written from the other sections and takes no sources.")
            raise HTTPException(422, f"{subject!r} is not a piece of {spec.title}. Its pieces are: "
                                     f"{', '.join(p.subject for p in pieces) or 'none yet'}.")
        return spec, period, piece

    def source_meta(piece, items: list[source_store.SourceText]) -> dict:
        return {"subject": piece.subject, "end": piece.end.isoformat(),
                "week_end": latest_friday(piece.end).isoformat(), "sources": [s.meta() for s in items],
                "gather": source_store.last_look(piece.subject, piece.end, d.sources_dir)}


    @router.get("/api/sources")
    def list_sources(
        section: str = Query(max_length=40),
        report_type: ReportType = Query(default=WEEKLY),
        period: Optional[str] = Query(default=None, max_length=40),
        subject: Optional[str] = Query(default=None, max_length=200),
        sections: Optional[str] = Query(default=None, max_length=4000),
    ) -> dict:
        """The pieces of one section (or the one named by ``subject``) with the sources saved for each.  ``sections`` is the
        Focus's typed titles, which are what name its pieces."""
        if subject:
            spec, _, first = source_piece(section, subject, report_type, period, sections)
            found = [first]
        else:
            period, _ = chosen_report(report_type, period, None)
            spec = spec_for(report_type, section)
            if spec is None:
                raise HTTPException(404, f"no section {section!r} in the {TYPES[report_type].title}")
            if not spec.available or not uses_provider(spec):
                return {"section": section, "title": spec.title, "uses_sources": False, "pieces": [],
                        "approved_sites": list(source_store.APPROVED_SITES)}
            try:
                titles = clean_sections(sections) if spec.needs_topic and sections and sections.strip() else []
                found = pieces_for(report_type, period, section, sections=titles, today=date.today()) or []
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        try:
            pieces = [source_meta(p, source_store.list_for(p.subject, p.end, d.sources_dir)) for p in found]
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        return {"section": section, "title": spec.title, "uses_sources": True, "pieces": pieces,
                "approved_sites": list(source_store.APPROVED_SITES)}

    @router.post("/api/sources")
    def add_source(body: SourceBody) -> dict:
        """Keep one source for a piece: with no ``text`` and no ``date`` the page at ``url`` is fetched (any site; the safety rules of common/sources.py apply);
        with them, the pasted text is kept as it is, under the address and date given.  422 with the reason if it is refused."""
        spec, period, piece = source_piece(body.section, body.subject, body.report_type, body.period, body.sections)
        d.refuse_while_drafting(piece.subject, latest_friday(piece.end).isoformat())
        pasted = bool((body.text or "").strip() or (body.date or "").strip())
        try:
            if pasted:
                added = source_store.from_paste(body.url, body.date or "", body.text or "", piece.subject, piece.end,
                                                title=body.title or "", root=d.sources_dir)
            else:
                added = d.fetch_source(body.url, piece.subject, piece.end, root=d.sources_dir)
            items = source_store.list_for(piece.subject, piece.end, d.sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(422, str(exc))
        return {"source": added.meta(), **source_meta(piece, items)}

    @router.get("/api/sources/{source_id}")
    def source_facts(source_id: str) -> dict:
        """One saved source's facts: what the list route returns for it, without the text (that is /text)."""
        try:
            src = source_store.get(source_id, d.sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        if src is None:
            raise HTTPException(404, f"no saved source {source_id!r}")
        return src.meta()

    @router.get("/api/sources/{source_id}/text")
    def source_text(source_id: str) -> Response:
        """The saved text of one source, as plain text: what the model was shown and what its quotes are checked against."""
        try:
            src = source_store.get(source_id, d.sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        if src is None:
            raise HTTPException(404, f"no saved source {source_id!r}")
        return Response(src.text, media_type="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @router.delete("/api/sources/{source_id}")
    def delete_source(source_id: str) -> dict:
        try:
            gone = source_store.get(source_id, d.sources_dir)
        except source_store.SourceError:
            gone = None
        if gone:
            d.refuse_while_drafting(gone.subject, gone.week_end)
        if not source_store.remove(source_id, d.sources_dir):
            raise HTTPException(404, f"no saved source {source_id!r}")
        if gone:   # the first look after a removal is not held back by the cooldown
            d.gather_stamps.pop((gone.week_end, source_store.subject_key(gone.subject)), None)
        return {"removed": source_id}


    @router.post("/api/sources/gather")
    def gather_sources(body: GatherBody) -> dict:
        """Run the gather step for one piece. 409 while a draft that reads the piece is running or queued. Once an hour per
        piece, except the first look after a source is removed. Answers with what was saved, how many, and the piece's sources."""
        _, _, piece = source_piece(body.section, body.subject, body.report_type, body.period, body.sections)
        d.refuse_while_drafting(piece.subject, latest_friday(piece.end).isoformat())
        key = (latest_friday(piece.end).isoformat(), source_store.subject_key(piece.subject))
        limits = source_gather.limits_from_env()
        reason, saved = None, []
        try:
            have = source_store.list_for(piece.subject, piece.end, d.sources_dir)
            last = d.gather_stamps.get(key)
            if len(have) >= limits.enough:
                reason = f"This piece already has {len(have)} sources, so none were looked for."
            elif last is not None and d.clock() - last < d.gather_cooldown:
                reason = "Sources were looked for less than an hour ago. Add one by hand, or search again later."
            else:
                saved, looked = source_gather.gather([piece], search=d.search_sources, fetch=d.fetch_source, root=d.sources_dir,
                                                     limits=limits)
                if looked:
                    d.gather_stamps[key] = d.clock()
                else:
                    reason = source_gather.NOT_CONFIGURED
            items = source_store.list_for(piece.subject, piece.end, d.sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        return {"found": len(saved), "reason": reason, "added": [s.meta() for s in saved], **source_meta(piece, items)}

    return router
