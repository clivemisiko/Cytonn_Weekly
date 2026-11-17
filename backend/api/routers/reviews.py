import logging
from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from cytonn_weekly.charts import store as chart_store
from cytonn_weekly.charts.block import set_team_chart
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview, rejected_draft_notes
from cytonn_weekly.report_sections import section_slug
from cytonn_weekly.report_types import WEEKLY
from cytonn_weekly.weekly import inputs as weekly_inputs
from cytonn_weekly.weekly import recheck as weekly_recheck
from cytonn_weekly.weekly import sentence_edit
from cytonn_weekly.weekly.week import Week
from api.problems import ProblemError
from api.serialize import serialize_review
from api.deps import Deps, failure_message
from api.schemas import ItemResolution, Decision, SentenceChange, TeamChartBody

log = logging.getLogger(__name__)


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/reviews/latest")
    def latest_review(
        run_date: Optional[str] = Query(
            default=None, description="ISO date, or 'today' (the server's today, which is also what a new draft is stamped with)"
        ),
    ) -> dict:
        if run_date is None:
            wanted = None
        elif run_date == "today":
            wanted = date.today()
        else:
            try:
                wanted = date.fromisoformat(run_date)
            except ValueError:
                raise HTTPException(422, f"run_date must be an ISO date or 'today', got {run_date!r}")
        review = review_store.load_latest_review(run_date=wanted, db_path=d.db_path)
        if review is None:
            raise HTTPException(404, "no saved review" + (f" for {wanted.isoformat()}" if wanted else ""))
        return serialize_review(review)


    @router.get("/api/reviews/{run_id}")
    def get_review(run_id: int) -> dict:
        return serialize_review(d.load(run_id))

    @router.get("/api/reviews/{run_id}/charts/{chart_id}.png")
    def chart_png(run_id: int, chart_id: str) -> Response:
        """A drawn chart's picture, only while it is the file the review recorded (its SHA-256 is checked on every read).

        ``chart_id`` must be a known chart (charts/specs.py), so no other path is ever read.  404 for an unknown
        chart, a review without that drawn chart, or a missing file; 409 when the file has changed since the draft.
        """
        review = d.load(run_id)
        block = next((b for b in review.section.get("blocks", []) if b.get("kind") == "chart" and b.get("chart_id") == chart_id), None)
        try:
            data = chart_store.read_png(run_id, chart_id, block and block.get("png_sha256"), d.charts_root)
        except chart_store.ChartFileError as exc:
            raise HTTPException(exc.status, str(exc))
        return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})

    @router.get("/api/reviews/{run_id}/charts/{chart_id}/series")
    def chart_series(run_id: int, chart_id: str) -> Response:
        """The series a drawn chart was drawn from (JSON), only while it is the file the review recorded: the same checks
        and answers as the picture (404 unknown chart, no such drawn chart or missing file; 409 for a changed file)."""
        review = d.load(run_id)
        block = next((b for b in review.section.get("blocks", []) if b.get("kind") == "chart" and b.get("chart_id") == chart_id), None)
        try:
            data = chart_store.read_series(run_id, chart_id, block and block.get("series_sha256"), d.charts_root)
        except chart_store.ChartFileError as exc:
            raise HTTPException(exc.status, str(exc))
        return Response(data, media_type="application/json", headers={"Cache-Control": "no-store"})

    @router.put("/api/reviews/{run_id}/charts/{chart_id}/team-chart")
    def team_chart(run_id: int, chart_id: str, body: TeamChartBody) -> dict:
        """Set the tool's chart aside for the team's own (``use`` true) or take that back (false).  Every item of the chart is
        accepted with a note saying so, or cleared; the choice is saved with the review.  409 once the review is decided,
        404 for a chart the review does not have, 409 for a chart nothing was read for (no workbook)."""
        def change(review: CoordinatorReview) -> None:
            try:
                set_team_chart(review, chart_id, body.use)
            except KeyError as exc:
                raise HTTPException(404, str(exc.args[0]))
            except ValueError as exc:
                raise HTTPException(409, str(exc))
        return d.mutate(run_id, change)

    @router.get("/api/reviews/{run_id}/rejected-draft-notes")
    def get_rejected_draft_notes(run_id: int) -> Optional[dict]:
        """The rejected draft just before this run (same section, report and period): its fix-needed items and notes.

        null when the run before was not rejected, held nothing to show, or there is none.  Read-only.
        """
        try:
            previous = review_store.load_previous_review(run_id, db_path=d.db_path)
        except KeyError:
            raise ProblemError(404, f"There is no saved review number {run_id}. Go back to the overview and open the section again.", "review_not_found")
        return rejected_draft_notes(previous)


    @router.patch("/api/reviews/{run_id}/items/{index}")
    def resolve_item(run_id: int, index: int, body: ItemResolution) -> dict:
        def change(review: CoordinatorReview) -> None:
            if not 0 <= index < len(review.review_items):
                raise HTTPException(404, f"run {run_id} has no review item {index}")
            item = review.review_items[index]
            if "note" in body.model_fields_set:
                note = (body.note or "").strip() or None
            else:
                note = item.resolution_note
            item.resolve(body.resolution, note)

        return d.mutate(run_id, change)


    @router.post("/api/reviews/{run_id}/items/{index}/fix-input")
    async def fix_from_input(run_id: int, index: int, request: Request, slot: str = Query(max_length=40),
                             filename: str = Query(default="", max_length=260)) -> dict:
        """Re-check a flagged item against a file the reviewer uploads (the file is the request body, as for an input upload).

        The file is checked and the section's figures re-read on a copy of the week's inputs, with no network and no model
        (weekly/recheck.py).  Only if that works is the file kept and a NEW undecided review saved; the earlier review is
        never edited.  Answers ``{"review", "result"}``.  The draft slot and the run registry are not touched.
        """
        old = d.load(run_id)
        section = section_slug(old)
        if old.report_type != WEEKLY or section not in weekly_recheck.SLOT_MAP or not 0 <= index < len(old.review_items) \
                or "week_ending" not in old.section:
            raise ProblemError(409, "This item cannot be fixed by adding a file.", "fix_not_possible")
        if slot not in weekly_recheck.fix_slots(section, old.section, old.review_items[index]):
            raise ProblemError(409, "That file does not feed this item, or the item is not one a file can fix. Open the item again.", "fix_not_possible")
        too_big = "The file is over the {} MB limit. Upload a smaller copy of the file.".format(weekly_inputs.MAX_BYTES // 1_048_576)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > weekly_inputs.MAX_BYTES:
            raise ProblemError(413, too_big, "fix_file_too_big")
        data = await request.body()
        if len(data) > weekly_inputs.MAX_BYTES:
            raise ProblemError(413, too_big, "fix_file_too_big")
        week = Week(date.fromisoformat(old.section["week_ending"]))
        try:
            done = await run_in_threadpool(weekly_recheck.recheck, old, slot, data, filename, d.root, d.charts_root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "fix_file_refused")
        except Exception as exc:  # noqa: BLE001 - shown to the reviewer; nothing was kept or saved
            log.exception("re-check of run %s from %s failed", run_id, slot)
            raise ProblemError(500, f"The figures could not be re-checked, so nothing was changed and the file was not kept. {failure_message(exc)}", "fix_check_failed")
        with d.write_lock:
            try:
                weekly_inputs.store(week, slot, data, filename, d.root)
            except weekly_inputs.InputError as exc:
                raise ProblemError(422, str(exc), "fix_file_refused")
            try:
                d.save(done.review)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("saving the re-checked review of run %s failed", run_id)
                raise ProblemError(500, "The file was kept among this week's inputs, but the new version could not be saved. "
                                        f"Try again. {failure_message(exc)}", "fix_check_failed")
        return {"review": serialize_review(done.review),
                "result": {"changes": done.changes, "changed_items": done.changed_items, "kept": done.kept,
                           "earlier_run_id": run_id, "slot": slot, "was_approved": old.decision == "approved"}}


    @router.post("/api/reviews/{run_id}/items/{index}/sentence")
    def change_sentence(run_id: int, index: int, body: SentenceChange) -> dict:
        """Rewrite or remove one flagged sentence of a drafted piece by hand: no model, no network.

        The figures are checked again with the same offline checker, and a NEW undecided review is saved (the earlier
        one is never edited, even if approved).  Answers ``{"review", "result"}``.  The draft slot and runs are not touched.
        """
        old = d.load(run_id)
        try:
            if body.action == "paragraph":   # a whole carried-forward paragraph, retyped by hand
                done = sentence_edit.apply_paragraph(old, index, body.text, d.charts_root)
            else:
                done = sentence_edit.apply(old, index, body.action, body.text, d.charts_root)
        except sentence_edit.TextRefused as exc:
            raise ProblemError(422, str(exc), "edit_text_refused")
        except (sentence_edit.NotFound, sentence_edit.NotPossible) as exc:
            if body.action == "paragraph":
                raise ProblemError(409, str(exc), "edit_paragraph_not_possible")
            if isinstance(exc, sentence_edit.NotFound):
                raise ProblemError(409, str(exc), "edit_sentence_not_found")
            raise ProblemError(409, str(exc), "edit_not_possible")
        except Exception:  # noqa: BLE001 - nothing was saved; the reviewer gets a fixed sentence, the log gets the cause
            log.exception("checking the %s of a sentence in run %s failed", body.action, run_id)
            raise ProblemError(500, sentence_edit.CHECK_FAILED, "edit_save_failed")
        with d.write_lock:
            try:
                d.save(done.review)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001
                log.exception("saving the %s of a sentence in run %s failed", body.action, run_id)
                raise ProblemError(500, sentence_edit.SAVE_FAILED, "edit_save_failed")
        return {"review": serialize_review(done.review),
                "result": {"action": done.action, "changed_items": done.changed_items, "earlier_run_id": run_id,
                           "was_approved": old.decision == "approved"}}


    @router.post("/api/reviews/{run_id}/items/{index}/remove-finding")
    def remove_finding(run_id: int, index: int) -> dict:
        """Take one whole drafted piece (a Digital Payments highlight, or a narrative piece) out of the draft.

        A NEW undecided review is saved without it, as for a sentence edit; the earlier one is never edited, even if
        approved.  Answers ``{"review", "result"}`` like the sentence route.
        """
        old = d.load(run_id)
        try:
            done = sentence_edit.remove_finding(old, index, d.charts_root)
        except sentence_edit.NotFound as exc:
            raise ProblemError(409, str(exc), "finding_not_found")
        except sentence_edit.NotPossible as exc:
            raise ProblemError(409, str(exc), "finding_not_possible")
        except Exception:  # noqa: BLE001 - nothing was saved; the reviewer gets a fixed sentence, the log gets the cause
            log.exception("removing a finding from run %s failed", run_id)
            raise ProblemError(500, sentence_edit.FINDING_SAVE_FAILED, "finding_save_failed")
        with d.write_lock:
            try:
                d.save(done.review)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001
                log.exception("saving run %s without a finding failed", run_id)
                raise ProblemError(500, sentence_edit.FINDING_SAVE_FAILED, "finding_save_failed")
        return {"review": serialize_review(done.review),
                "result": {"action": done.action, "changed_items": done.changed_items, "earlier_run_id": run_id,
                           "was_approved": old.decision == "approved"}}


    @router.post("/api/reviews/{run_id}/accept-clean")
    def accept_clean(run_id: int) -> dict:
        return d.mutate(run_id, lambda review: review.accept_all_clean())


    @router.post("/api/reviews/{run_id}/decide")
    def decide(run_id: int, body: Decision) -> dict:
        with d.write_lock:
            review = d.load(run_id)
            try:
                review.decide(body.decision, body.acknowledged_flagged)  # ValueError: not approvable, already decided, or flagged items not acknowledged
            except ValueError as exc:
                raise ProblemError(409, str(exc), "review_not_decidable")
            d.save(review)
            return serialize_review(review)

    return router
