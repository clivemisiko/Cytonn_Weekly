from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.digital_payments import review_run
from cytonn_weekly.review.model import CoordinatorReview
from cytonn_weekly.narrative import bedrock_provider
from cytonn_weekly.periodic.executive_summary import SectionsNotApproved
from cytonn_weekly.source_pieces import pieces_for
from cytonn_weekly.report_types import TYPES
from cytonn_weekly.weekly.week import latest_friday
from api.problems import ProblemError
from api.draft_slot import Claim, DraftBusy
from api.runs import QUEUED, RUNNING, RunAlreadyRunning
from api.deps import Deps, failure_message, provider_label, provider_problem, uses_provider
from api.schemas import DraftRequest, RunRequest


def make_router(d: Deps) -> APIRouter:
    router = APIRouter()

    @router.post("/api/reviews/draft")
    def draft_review() -> dict:
        """Run the real pipeline (price fetch, drafting, checking) and save the result.

        Takes minutes, and spends real API budget unless CYTONN_LLM_PROVIDER=local.  The
        draft is saved on the server even if the client gives up waiting, so the start
        screen can offer it for resume afterwards.
        """
        def build() -> CoordinatorReview:
            try:
                with bedrock_provider.track_usage() as used:
                    review = review_run.build_digital_payments_review()
                if used.calls:
                    review.section["usage"] = bedrock_provider.usage_record(used, bedrock_provider.model_id())
                return review
            except Exception as exc:  # noqa: BLE001 - shown to the analyst, not swallowed
                raise ProblemError(502, f"The draft stopped. {failure_message(exc)}", "draft_failed")

        return d.run_draft("digital_payments", build)

    @router.post("/api/sections/{slug}/draft")
    def draft_section(slug: str, body: Optional[DraftRequest] = None) -> dict:
        """Run one section's real pipeline for one report and period, and save the result.

        Same guards as /api/reviews/draft.  The Executive Summary calls
        no provider, so it needs no API key and takes no draft slot; the summary refuses
        (409, naming each section) until every section it summarises is approved.
        """
        spec, ctx, report_type, period = d.resolve_draft(slug, body or DraftRequest())

        def build() -> CoordinatorReview:
            try:
                return d.build_tracked(spec, ctx, report_type, period)
            except SectionsNotApproved as exc:
                raise ProblemError(409, str(exc), "draft_sections_not_approved")
            except ValueError as exc:  # e.g. an unusable Focus topic
                raise ProblemError(422, str(exc), "draft_input_invalid")
            except Exception as exc:  # noqa: BLE001 - shown to the analyst, not swallowed
                raise ProblemError(502, f"The draft stopped. {failure_message(exc)}", "draft_failed")

        if not uses_provider(spec):
            return d.run_quick(build)
        return d.run_draft(slug, build, report_type, period)


    @router.post("/api/runs", status_code=202)
    def start_run(body: RunRequest) -> dict:
        """Start one section's draft in a worker thread and return its run id at once.

        Takes what POST /api/sections/{slug}/draft takes (with the section in the body) and
        refuses the same things before anything starts.  409 if this section of this report
        is already running or queued here, or if ``provider`` names a provider the API is not
        configured for.  With every drafting seat taken the run waits in the queue (202,
        ``state: "queued"``, ``position``); 429 when the queue is full.  A failure once the draft is under
        way (sections not yet approved for an Executive Summary, a source that is down) is
        the run's ``run_failed`` event, not an HTTP error.
        """
        spec, ctx, report_type, period = d.resolve_draft(body.section, body)
        if body.provider is not None and body.provider.strip().lower() != provider_label():
            raise ProblemError(
                409,
                "The tool's drafting mode changed after this page was opened. Reload the page to see what a draft "
                "will use, then start it again.",
                "draft_mode_changed")
        needs_seat = uses_provider(spec)
        if needs_seat:
            problem = provider_problem()
            if problem:
                raise ProblemError(409, problem, "drafting_off")
        try:   # the sources this draft reads, so a change to another section's sources is not held up by it
            piece_keys = frozenset((source_store.subject_key(p.subject), latest_friday(p.end).isoformat()) for p in
                                   (pieces_for(report_type, period, spec.slug, sections=ctx.sections, today=date.today()) or [])) \
                if needs_seat else frozenset()
        except Exception:  # noqa: BLE001 - a piece list that cannot be built only means no source is held back
            piece_keys = frozenset()
        with d.seats:
            try:
                run = d.runs.start(report_type, period, spec.slug, spec.title, TYPES[report_type].title, d.clock(),
                                 status=QUEUED if needs_seat else RUNNING)
            except RunAlreadyRunning:
                raise ProblemError(
                    409,
                    f"{spec.title}{f' for {period}' if period else ''} is already being drafted or is queued. It is saved when "
                    "it finishes, and the overview shows it until then. Wait for it, then open it from the overview.",
                    "draft_already_running")
            run.piece_keys = piece_keys
            claim: Optional[Claim] = None
            if needs_seat:
                if not d.waiting:   # nobody is ahead of this run
                    try:
                        claim = d.take_seat(spec.slug, report_type, period)
                    except DraftBusy:
                        pass
                if claim is None:
                    if len(d.waiting) >= d.queue_max:
                        d.runs.discard(run)
                        raise HTTPException(429, f"The draft queue is full ({d.queue_max} waiting). Try again when one of the "
                                                 "drafts has finished.")
                    d.waiting.append((run, spec, ctx))
                else:
                    run.begin(d.clock())
            position = next((i + 1 for i, (r, _, _) in enumerate(d.waiting) if r is run), None)
        if claim is not None or not needs_seat:
            d.launch(run, spec, ctx, claim)
        return {"run_id": run.run_id, "state": run.status, "position": position}

    @router.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict:
        """Take a queued run out of the queue.  A running draft cannot be stopped (409): it is saved when it finishes."""
        run = d.find_run(run_id)
        with d.seats:
            at = next((i for i, (r, _, _) in enumerate(d.waiting) if r is run), None)
            if at is not None:
                del d.waiting[at]
        if at is None:
            raise HTTPException(409, "A running draft cannot be stopped. It is saved when it finishes."
                                if run.status == RUNNING else "This draft has already ended, so there is nothing to cancel.")
        run.fail("Cancelled while it waited for a drafting seat, before it started. Nothing was drafted.")
        return {"run_id": run.run_id, "status": run.status}

    @router.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        """The run's status, every event so far, and (once finished) the saved review's id and dev-draft mark.  A queued run
        carries its ``position`` (1 is next)."""
        run = d.find_run(run_id)
        out = run.to_dict()
        if run.status == RUNNING:  # the server's count, so a screen that opens late or reloads still shows the true time
            out["elapsed_seconds"] = max(0, int(d.clock() - run.started_at))
            out["stale"] = out["elapsed_seconds"] >= d.draft_stale_after
        out["position"] = d.queue_position(run) if run.status == QUEUED else None
        return out

    @router.get("/api/runs/{run_id}/events")
    def run_events(run_id: str) -> StreamingResponse:
        """Server-Sent Events: the events already recorded, then each new one, closing after the run ends."""
        return StreamingResponse(
            d.find_run(run_id).stream(d.run_keepalive),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
