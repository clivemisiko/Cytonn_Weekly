"""FastAPI app for the coordinator review of every report section.

Digital Payments was the first section and keeps its original endpoints
(/api/reviews/latest, /api/reviews/draft), which are the weekly report's.  Every
section of every report type is reachable through /api/sections (the overview, for one
report type and period) and /api/sections/{slug}/draft (report type and period in the
body); each section's review is still its own CoordinatorReview, keyed by report type,
period and slug, and the per-review endpoints below (/api/reviews/{run_id}/...) work
for any of them.  /api/report-types lists the types and the companion report kinds.

/api/runs starts the same draft in a worker thread and answers at once with a run id;
/api/runs/{run_id}/events streams what the draft reports about itself as it happens
(common/run_events.py) and /api/runs/{run_id} returns the same as plain JSON.  The runs
live in memory only (api/runs.py).  The synchronous draft routes above are unchanged.

Run from backend/ (the package is installed editable):

    uvicorn api.main:app --port 8000

Every write endpoint is stateless: it loads the review fresh from review_store, mutates
it with the coordinator_review methods, saves it, and returns the whole updated review,
the same read-modify-write the Streamlit screen did per callback.  This module adds
three guards the store does not provide on its own:

* a decided review is read-only here.  review_store only rejects a save that disagrees
  with the stored decision, and a freshly loaded decided review agrees with it, so
  without this check its items could still be rewritten;
* writes run one at a time (one process-wide lock), because two quick clicks arrive as
  two concurrent requests and each one rewrites the whole items blob;
* only one draft runs at a time, across every section, because a draft takes minutes and
  (in anthropic mode) spends real API budget, so a double click or a second tab must not
  start another.  The slot (api/draft_slot.py) records which section holds it and since
  when, so the overview can show a running draft, and it expires a claim that has run
  far longer than any healthy draft, so a hung draft cannot block drafting forever.

The tool never approves anything: /decide only records the coordinator's call, and
CoordinatorReview.decide() decides whether it is allowed.
"""

import logging
import os
import re
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Callable, Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cytonn_weekly.common.run_events import RUN_STARTED, describe, review_counts
from cytonn_weekly.digital_payments import review_run, review_store
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.digital_payments.provider_factory import ENV_VAR as PROVIDER_ENV_VAR
from cytonn_weekly.env import load_env
from cytonn_weekly.focus.review_run import clean_topic
from cytonn_weekly.periodic.executive_summary import SectionsNotApproved
from cytonn_weekly.report_sections import (
    DraftContext,
    SectionSpec,
    companion_kinds,
    is_current,
    is_this_week,
    latest_runs,
    section_slug,
    sections_for,
    spec_for,
)
from cytonn_weekly.report_types import (
    COMPANION,
    REPORT_TYPES,
    TYPES,
    WEEKLY,
    PeriodError,
    normalize_period,
    suggested_period,
)

from api.draft_slot import DRAFT_STALE_AFTER_SECONDS, Claim, DraftBusy, DraftSlot, busy_message
from api.runs import SSE_KEEPALIVE_SECONDS, Run, RunAlreadyRunning, RunRegistry
from api.serialize import DEV_MODE_LABEL, is_dev_draft, serialize_review

log = logging.getLogger(__name__)

CORS_ENV_VAR = "CYTONN_WEB_ORIGINS"
DEFAULT_WEB_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


DISCARDED_AS_STUCK = (
    "This draft ran so long it was treated as stuck and a newer draft replaced it; its result was discarded."
)
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)


def configured_provider() -> str:
    return (os.environ.get(PROVIDER_ENV_VAR) or "anthropic").strip().lower()


def failure_message(exc: BaseException) -> str:
    """Why a run stopped, as one line for the screen: the error's own message, no traceback, no secrets.

    A ValueError is the pipeline talking to the coordinator (an unusable topic, sections not
    yet approved), so its message stands alone, as the draft route shows it; anything else
    is named by its type.  Any configured secret that an error message happens to quote is
    removed before it is recorded.
    """
    text = " ".join(str(exc).split()) if isinstance(exc, ValueError) else describe(exc)
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name) and len(value) >= 8:
            text = text.replace(value, "[redacted]")
    return text[:600]


def provider_problem() -> Optional[str]:
    """Why a draft cannot run with the configured provider, or None.

    Checked before a draft claims the slot or fetches anything: without it, a production
    draft with no key fetched every source first and then failed inside the Anthropic SDK
    with "Could not resolve authentication method", which tells a coordinator nothing.
    Local mode is not checked here: its Exa results may all be cached, so a missing
    EXA_API_KEY is not necessarily fatal, and the local provider reports it itself.
    """
    provider = configured_provider()
    if provider not in ("anthropic", "local"):
        return f"Unknown {PROVIDER_ENV_VAR} value {provider!r}; expected 'anthropic' or 'local'."
    if provider == "anthropic" and not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return (
            "Production drafting needs ANTHROPIC_API_KEY, and none is set (in .env or the shell). Add the key once "
            f"API budget is approved, or set {PROVIDER_ENV_VAR}=local to draft in dev mode (Ollama + Exa, never "
            "for publication). Restart the API after changing .env."
        )
    return None


class ItemResolution(BaseModel):
    """``resolution`` is required (null clears it).  An omitted ``note`` keeps the item's
    existing note; a present one replaces it (blank or null clears it)."""

    resolution: Optional[Literal["accept", "fix_needed"]]
    note: Optional[str] = Field(default=None, max_length=2000)


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]


ReportType = Literal["weekly", "quarterly", "half_year", "annual", "companion"]


class DraftRequest(BaseModel):
    """``topic`` is required for Focus of the Week and ``text`` for Company Updates; other sections ignore both.

    ``report_type`` and ``period`` say which report the section belongs to.  The default,
    the weekly report with no period label, is what every draft was before report types.
    """

    # No length here: clean_topic() is the one place a topic's length is judged (resolve_draft calls it),
    # so the API and the pipeline refuse the same topics in the same words.
    topic: Optional[str] = None
    text: Optional[str] = Field(default=None, max_length=10_000)
    report_type: ReportType = WEEKLY
    period: Optional[str] = Field(default=None, max_length=40)
    kind: Optional[str] = Field(default=None, max_length=40)


class RunRequest(DraftRequest):
    """POST /api/runs: the draft route's inputs, with the section in the body.

    ``provider`` is optional and only ever a check: the provider the screen told the
    coordinator a draft would use ("anthropic" spends API budget, "local" is dev mode).
    If the API is configured for a different one, the run is refused rather than started
    on a provider the coordinator did not see.  It never selects the provider; only
    CYTONN_LLM_PROVIDER does.
    """

    section: str = Field(min_length=1, max_length=80)
    provider: Optional[str] = Field(default=None, max_length=40)


def uses_provider(spec: SectionSpec) -> bool:
    """Whether drafting the section calls the LLM provider (Company Updates and the Executive Summary never do)."""
    return not (spec.needs_text or spec.requires_approved)


def report_label(report_type: str, period: str) -> str:
    return period or TYPES[report_type].title


def create_app(
    db_path: Optional[Union[Path, str]] = None,
    *,
    load_dotenv: bool = True,
    draft_stale_after: float = DRAFT_STALE_AFTER_SECONDS,
    clock: Callable[[], float] = time.time,
    run_keepalive: float = SSE_KEEPALIVE_SECONDS,
) -> FastAPI:
    """Build the app.  ``db_path`` defaults to data/app.db; tests pass a temp file.

    ``draft_stale_after`` and ``clock`` set when a running draft counts as stuck
    (api/draft_slot.py); tests pass a fake clock instead of waiting an hour.  ``run_keepalive``
    is how often an idle run stream sends its keepalive comment (api/runs.py).

    ``load_dotenv`` loads the repo-root .env first, before anything here reads os.environ,
    as every entrypoint does: CYTONN_WEB_ORIGINS is read right below, and the pipeline
    reads CYTONN_LLM_PROVIDER and the API keys.  (It used to load in the startup hook,
    after the origins were read, so CYTONN_WEB_ORIGINS only worked from the shell.)
    Library code only reads os.environ.
    """
    if load_dotenv:
        load_env(quiet=True)

    app = FastAPI(title="Cytonn Weekly: coordinator review")
    origins = [o.strip() for o in os.environ.get(CORS_ENV_VAR, DEFAULT_WEB_ORIGINS).split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    write_lock = threading.Lock()
    draft_slot = DraftSlot(stale_after=draft_stale_after, clock=clock)
    runs = RunRegistry()  # in memory only: a restart forgets every run (api/runs.py)

    # -- helpers ----------------------------------------------------------

    def load(run_id: int) -> CoordinatorReview:
        try:
            return review_store.load_review(run_id, db_path=db_path)
        except KeyError:
            raise HTTPException(404, f"no saved review with run_id {run_id}")

    def save(review: CoordinatorReview) -> None:
        try:
            review_store.save_review(review, section=section_slug(review), db_path=db_path)
        except review_store.ReviewAlreadyDecided as exc:
            raise HTTPException(409, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))

    def mutate(run_id: int, change) -> dict:
        """Load, refuse if already decided, apply ``change(review)``, save, return the review."""
        with write_lock:
            review = load(run_id)
            if review.decision is not None:
                raise HTTPException(409, f"run {run_id} was already {review.decision}; it cannot be changed")
            change(review)
            save(review)
            return serialize_review(review)

    def stamp(review: CoordinatorReview, report_type: str, period: str) -> CoordinatorReview:
        """Set the review's key before its first save (a weekly build knows nothing of report types)."""
        review.report_type, review.period = report_type, period
        return review

    def run_quick(build: Callable[[], CoordinatorReview]) -> dict:
        """A section that neither searches nor calls the LLM (Company Updates, the Executive Summary).

        It takes no draft slot: it finishes at once and spends nothing, so a long draft of
        another section must not hold it up.
        """
        review = build()
        with write_lock:
            save(review)
        return serialize_review(review)

    def run_draft(slug: str, build: Callable[[], CoordinatorReview], report_type: str = WEEKLY,
                  period: str = "") -> dict:
        """Claim the one draft slot, run ``build``, save the result at once, and free the slot.

        A fresh draft is saved before it is returned, so a closed tab never loses a paid run.
        The one exception is a run that held the slot so long it was taken over as stuck: its
        result is discarded (see api/draft_slot.py), because saving it would put an abandoned
        run over the newer draft that replaced it.
        """
        claim = claim_slot(slug, report_type, period)
        try:
            review = build()
        except BaseException:
            draft_slot.release(claim)
            raise
        if not draft_slot.release(claim):
            log.warning("draft of %s finished after it was replaced as stuck; its result was discarded", slug)
            raise HTTPException(409, DISCARDED_AS_STUCK)
        with write_lock:
            save(review)
        return serialize_review(review)

    def claim_slot(slug: str, report_type: str, period: str) -> Claim:
        """Refuse a draft the provider cannot run (409), then take the one draft slot (409 if another holds it)."""
        problem = provider_problem()
        if problem:
            raise HTTPException(409, problem)
        title = spec_for(report_type, slug).title
        if report_type != WEEKLY or period:
            title = f"{title} ({report_label(report_type, period)})"
        try:
            claim, replaced = draft_slot.claim(slug, title, report_type, period)
        except DraftBusy as exc:
            raise HTTPException(409, busy_message(exc))
        if replaced is not None:
            log.warning("draft of %s (started %.0fs ago) was treated as stuck and replaced by a draft of %s",
                        replaced.slug, claim.started_at - replaced.started_at, slug)
        return claim

    def resolve_draft(slug: str, body: DraftRequest) -> tuple[SectionSpec, DraftContext, str, str]:
        """Validate one draft request: (the section's spec, its draft context, the report type, the normalized period).

        Both ways of starting a draft (the synchronous route and a run) go through this, so
        they refuse the same things with the same words: a period that does not fit the type
        (422), an unknown section (404), an unavailable one (409), a missing topic or text (422).
        """
        report_type = body.report_type
        period, kind = chosen_report(report_type, body.period, body.kind)
        spec = spec_for(report_type, slug, kind)
        if spec is None:
            raise HTTPException(404, f"no section {slug!r} in the {TYPES[report_type].title}")
        if not spec.available or spec.build is None:
            raise HTTPException(409, f"{spec.title} cannot be drafted yet: {spec.reason}")
        topic = body.topic or None
        if spec.needs_topic and not (topic and topic.strip()):
            raise HTTPException(422, f"{spec.title} needs a topic to draft")
        if topic and topic.strip():
            try:
                topic = clean_topic(topic)  # whitespace-normalized; over focus.review_run.MAX_TOPIC_CHARS is refused
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        if spec.needs_text and not (body.text and body.text.strip()):
            raise HTTPException(422, f"{spec.title} needs your text to draft")
        ctx = DraftContext(report_type=report_type, period=period, topic=topic, text=body.text, db_path=db_path)
        return spec, ctx, report_type, period

    def find_run(run_id: str) -> Run:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id!r}; runs are kept in memory and are lost when the API restarts")
        return run

    def work_run(run: Run, spec: SectionSpec, ctx: DraftContext, claim: Optional[Claim]) -> None:
        """The worker thread of one run: the draft route's build, release and save, reported to the run.

        Same builder, same stamp, same save as the draft route, so the review it leaves is the
        same review.  The run is finished only once that review is saved; every other way out
        is ``run_failed`` with the reason.
        """
        run.record(RUN_STARTED, spec.title)
        try:
            review = stamp(spec.build(replace(ctx, on_event=run.record)), ctx.report_type, ctx.period)
        except BaseException as exc:
            if claim is not None:
                draft_slot.release(claim)
            run.fail(failure_message(exc))
            if not isinstance(exc, Exception):
                raise
            log.warning("run %s (%s) failed: %s", run.run_id, spec.slug, describe(exc))
            return
        if claim is not None and not draft_slot.release(claim):
            log.warning("draft of %s finished after it was replaced as stuck; its result was discarded", spec.slug)
            run.fail(DISCARDED_AS_STUCK)
            return
        try:
            with write_lock:
                review_store.save_review(review, section=section_slug(review), db_path=db_path)
            dev = is_dev_draft(review)
            run.finish(review.run_id, review_counts(review), dev, DEV_MODE_LABEL if dev else None)
        except Exception as exc:  # noqa: BLE001 - the run must end, and say why
            log.exception("run %s (%s) could not save its review", run.run_id, spec.slug)
            run.fail(failure_message(exc))

    # -- reads ------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/config")
    def config() -> dict:
        """What the start screen needs before any review exists: who would draft, and at what cost."""
        provider = (os.environ.get(PROVIDER_ENV_VAR) or "anthropic").strip().lower()
        return {
            "provider": provider,
            "provider_valid": provider in ("anthropic", "local"),
            "dev_mode": provider == "local",
            "dev_mode_label": DEV_MODE_LABEL,
            "spends_api_budget": provider == "anthropic",
            "provider_problem": provider_problem(),
        }

    @app.get("/api/reviews/latest")
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
        review = review_store.load_latest_review(run_date=wanted, db_path=db_path)
        if review is None:
            raise HTTPException(404, "no saved review" + (f" for {wanted.isoformat()}" if wanted else ""))
        return serialize_review(review)

    def report_types() -> list[dict]:
        today = date.today()
        return [{"slug": t, "title": TYPES[t].title, "published_as": TYPES[t].published_as,
                 "period_hint": TYPES[t].period_hint, "period_required": TYPES[t].period_required,
                 "suggested_period": suggested_period(t, today)} for t in REPORT_TYPES]

    def chosen_report(report_type: str, period: Optional[str], kind: Optional[str]) -> tuple[str, Optional[str]]:
        """The normalized period (422 if it does not fit the type) and the companion kind (422 if unknown)."""
        try:
            normalized = normalize_period(report_type, period)
        except PeriodError as exc:
            raise HTTPException(422, str(exc))
        if report_type == COMPANION and kind is not None and kind not in {k["slug"] for k in companion_kinds()}:
            raise HTTPException(422, f"unknown companion report kind {kind!r}")
        return normalized, kind

    @app.get("/api/report-types")
    def list_report_types() -> dict:
        return {"report_types": report_types(), "companion_kinds": companion_kinds()}

    @app.get("/api/sections")
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
        runs = latest_runs(db_path, report_type, period)
        today = date.today()
        out = []
        for spec in sections_for(report_type, kind):
            latest = None
            run = runs.get(spec.slug)
            if run is not None:
                review = load(run["run_id"])
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
                "needs_text": spec.needs_text, "requires_approved": spec.requires_approved,
                "uses_provider": uses_provider(spec),
                "reason": spec.reason or None, "unblock": spec.unblock or None, "built_parts": list(spec.built_parts),
                "subsections": list(spec.subsections), "charts": list(spec.charts),
                "steps": [{"title": t, "body": b} for t, b in spec.steps], "latest": latest,
            })
        report = {"type": report_type, "title": TYPES[report_type].title, "period": period, "kind": kind,
                  "published_as": TYPES[report_type].published_as}
        # The draft running right now, if any (one at a time across every section and report): it
        # is not saved until it finishes, so without this the overview could not show it at all.
        return {"today": today.isoformat(), "drafting": draft_slot.status(), "report": report,
                "report_types": report_types(), "companion_kinds": companion_kinds(), "sections": out}

    @app.get("/api/reviews/{run_id}")
    def get_review(run_id: int) -> dict:
        return serialize_review(load(run_id))

    # -- writes -----------------------------------------------------------

    @app.post("/api/reviews/draft")
    def draft_review() -> dict:
        """Run the real pipeline (price fetch, drafting, checking) and save the result.

        Takes minutes, and spends real API budget unless CYTONN_LLM_PROVIDER=local.  The
        draft is saved on the server even if the client gives up waiting, so the start
        screen can offer it for resume afterwards.
        """
        def build() -> CoordinatorReview:
            try:
                return review_run.build_digital_payments_review()
            except Exception as exc:  # noqa: BLE001 - shown to the coordinator, not swallowed
                raise HTTPException(502, f"The draft run failed: {type(exc).__name__}: {exc}")

        return run_draft("digital_payments", build)

    @app.post("/api/sections/{slug}/draft")
    def draft_section(slug: str, body: Optional[DraftRequest] = None) -> dict:
        """Run one section's real pipeline for one report and period, and save the result.

        Same guards as /api/reviews/draft.  The Executive Summary and Company Updates call
        no provider, so they need no API key and take no draft slot; the summary refuses
        (409, naming each section) until every section it summarises is approved.
        """
        spec, ctx, report_type, period = resolve_draft(slug, body or DraftRequest())

        def build() -> CoordinatorReview:
            try:
                return stamp(spec.build(ctx), report_type, period)
            except SectionsNotApproved as exc:
                raise HTTPException(409, str(exc))
            except ValueError as exc:  # e.g. an unusable Focus topic, or missing Company Updates text
                raise HTTPException(422, str(exc))
            except Exception as exc:  # noqa: BLE001 - shown to the coordinator, not swallowed
                raise HTTPException(502, f"The draft run failed: {type(exc).__name__}: {exc}")

        if not uses_provider(spec):
            return run_quick(build)
        return run_draft(slug, build, report_type, period)

    # -- runs: the same draft, started in the background and watched as it happens ----

    @app.post("/api/runs", status_code=202)
    def start_run(body: RunRequest) -> dict:
        """Start one section's draft in a worker thread and return its run id at once.

        Takes what POST /api/sections/{slug}/draft takes (with the section in the body) and
        refuses the same things before anything starts.  409 if this section of this report
        is already running here, if another draft holds the one draft slot, or if ``provider``
        names a provider the API is not configured for.  A failure once the draft is under
        way (sections not yet approved for an Executive Summary, a source that is down) is
        the run's ``run_failed`` event, not an HTTP error.
        """
        spec, ctx, report_type, period = resolve_draft(body.section, body)
        if body.provider is not None and body.provider.strip().lower() != configured_provider():
            raise HTTPException(
                409,
                f"This screen expected the {body.provider.strip().lower()} drafting provider, but the API is configured "
                f"for {configured_provider()}. Reload the page to see what a draft will use, then start it again.",
            )
        try:
            run = runs.start(report_type, period, spec.slug, spec.title, TYPES[report_type].title)
        except RunAlreadyRunning:
            raise HTTPException(
                409,
                f"A draft of {spec.title}{f' for {period}' if period else ''} is already running. "
                "It is saved when it finishes, and the overview shows it until then.",
            )
        claim: Optional[Claim] = None
        if uses_provider(spec):
            try:
                claim = claim_slot(spec.slug, report_type, period)
            except HTTPException:
                runs.discard(run)
                raise
        threading.Thread(target=work_run, args=(run, spec, ctx, claim), name=f"run-{run.run_id[:8]}", daemon=True).start()
        return {"run_id": run.run_id}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        """The run's status, every event so far, and (once finished) the saved review's id and dev-draft mark."""
        return find_run(run_id).to_dict()

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str) -> StreamingResponse:
        """Server-Sent Events: the events already recorded, then each new one, closing after the run ends."""
        return StreamingResponse(
            find_run(run_id).stream(run_keepalive),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.patch("/api/reviews/{run_id}/items/{index}")
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

        return mutate(run_id, change)

    @app.post("/api/reviews/{run_id}/accept-clean")
    def accept_clean(run_id: int) -> dict:
        return mutate(run_id, lambda review: review.accept_all_clean())

    @app.post("/api/reviews/{run_id}/decide")
    def decide(run_id: int, body: Decision) -> dict:
        with write_lock:
            review = load(run_id)
            try:
                review.decide(body.decision)  # raises ValueError if not approvable or already decided
            except ValueError as exc:
                raise HTTPException(409, str(exc))
            save(review)
            return serialize_review(review)

    return app


def __getattr__(name: str):
    """``api.main:app``, built on first access (uvicorn's getattr), not at import.

    create_app() loads the real .env into os.environ, so building the app at import would
    leak a developer's .env into every test that merely imports create_app.
    """
    if name == "app":
        globals()["app"] = application = create_app()
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
