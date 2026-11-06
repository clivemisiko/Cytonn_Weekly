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

/api/inputs/weekly/{week_ending} is "This week's inputs": the files a coordinator uploads
for one report week (cytonn_weekly/weekly/inputs.py).  An upload is sent as the request
body itself (no multipart form), checked, and kept under the data directory.
/api/inputs/weekly/{week_ending}/analyst is the "Weekly analyst inputs" form beside them: the
figures only the analysts hold, typed when no workbook is sent (cytonn_weekly/weekly/analyst.py).

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
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Sequence, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from cytonn_weekly.charts import store as chart_store
from cytonn_weekly.charts.block import set_team_chart
from cytonn_weekly.common import gather as source_gather
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.common.run_events import RUN_STARTED, describe, redact, review_counts, safe_describe, user_message
from cytonn_weekly.digital_payments import review_run, review_store
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview, rejected_draft_notes
from cytonn_weekly.digital_payments.provider_factory import ENV_VAR as PROVIDER_ENV_VAR
from cytonn_weekly.digital_payments.providers.local_provider import EXA_KEY_ENV_VAR, EXA_KEY_MISSING, SearchKeyError
from cytonn_weekly.env import key_override_warnings, load_env
from cytonn_weekly.focus.review_run import clean_sections, clean_topic
from cytonn_weekly import db as database
from cytonn_weekly import notable
from cytonn_weekly.narrative import bedrock_provider
from cytonn_weekly.notable import store as notable_store
from cytonn_weekly.notable.registry import Detector, DetectorContext, run_detectors
from cytonn_weekly.notable.suggestion import MAX_HEADLINE
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
from cytonn_weekly.source_pieces import pieces_for
from cytonn_weekly.report_types import (
    COMPANION,
    REPORT_TYPES,
    TYPES,
    WEEKLY,
    PeriodError,
    normalize_period,
    suggested_period,
    week_ending_of,
)
from cytonn_weekly.weekly import cbk_bulletin, cbk_rates
from cytonn_weekly.weekly import export as weekly_export
from cytonn_weekly.weekly import analyst as weekly_analyst
from cytonn_weekly.weekly import chart_uploads
from cytonn_weekly.weekly import inputs as weekly_inputs
from cytonn_weekly.weekly import recheck as weekly_recheck
from cytonn_weekly.weekly import sentence_edit
from cytonn_weekly.weekly.week import NotAFriday, Week, latest_friday

from api.problems import ProblemError, problem_handler
from api.draft_slot import DRAFT_STALE_AFTER_SECONDS, Claim, DraftBusy, DraftSlot, busy_message
from api.runs import RUNNING, SSE_KEEPALIVE_SECONDS, Run, RunAlreadyRunning, RunRegistry
from api.serialize import DEV_MODE_LABEL, is_dev_draft, serialize_review

log = logging.getLogger(__name__)

CORS_ENV_VAR = "CYTONN_WEB_ORIGINS"
DEFAULT_WEB_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


DISCARDED_AS_STUCK = (
    "This draft ran so long that it was treated as stuck, and a newer draft replaced it. Its result was not saved. "
    "Open the section to see the newer draft."
)

PROVIDERS = ("anthropic", "bedrock", "local")
SECTIONS_REQUIRED = (
    "With Amazon Bedrock the model searches nothing, so it cannot propose the section titles from the topic alone. Type "
    "the section titles for this Focus (one a line, up to 8), supply the pages to read for each, then start the draft.")


def configured_provider() -> str:
    return (os.environ.get(PROVIDER_ENV_VAR) or "anthropic").strip().lower()


def failure_message(exc: BaseException) -> str:
    """Why a run stopped, as one line for the screen: the error's own message, no traceback, no secrets.

    A ValueError is the pipeline talking to the coordinator (an unusable topic, sections not
    yet approved), so its message stands alone, as the draft route shows it; so is a
    SearchKeyError (the web-search key is missing or was refused).  Anything else is named
    by its type.  Any configured secret that an error message happens to quote is removed
    before it is recorded.
    """
    if isinstance(exc, (ValueError, SearchKeyError, bedrock_provider.BedrockError)):
        text = " ".join(str(exc).split())
    else:
        text = user_message(exc)
        if text == redact(describe(exc)):   # not a connection or database failure: drop the class name, keep the redacted words
            detail = text.removeprefix(f"{type(exc).__name__}:").strip() or "no detail"
            return (f"An unexpected error occurred ({detail}). Try again; if it happens again, report it with the "
                    "section name.")[:600]
    return redact(text)[:600]


def provider_problem() -> Optional[str]:
    """Why a draft cannot run with the configured provider, or None.

    Checked before a draft claims the slot or fetches anything: without it, a production
    draft with no key fetched every source first and then failed inside the Anthropic SDK
    with "Could not resolve authentication method", which tells a coordinator nothing.
    Local mode is checked the same way for its web-search key: every section but Digital
    Payments searches afresh each draft, and Digital Payments' cache lasts one day.  Only
    a missing key is known here; a key Exa refuses is reported by the search itself.
    """
    provider = configured_provider()
    if provider not in PROVIDERS:
        return f"Unknown {PROVIDER_ENV_VAR} value {provider!r}; expected 'anthropic', 'bedrock' or 'local'."
    if provider == "bedrock":
        return bedrock_provider.env_problem()
    if provider == "anthropic" and not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return (
            "Production drafting needs ANTHROPIC_API_KEY, and none is set (in .env or the shell). Add the key once "
            f"API budget is approved, or set {PROVIDER_ENV_VAR}=local to draft in dev mode (Ollama + Exa, never "
            "for publication). Restart the API after changing .env."
        )
    if provider == "anthropic" and not (os.environ.get("CYTONN_LLM_MODEL") or "").strip():
        return "CYTONN_LLM_MODEL is not set (in .env or the shell). Set it to the Claude model to draft with. Restart the API after changing .env."
    if provider == "local" and not (os.environ.get(EXA_KEY_ENV_VAR) or "").strip():
        return EXA_KEY_MISSING
    return None


class ItemResolution(BaseModel):
    """``resolution`` is required (null clears it).  An omitted ``note`` keeps the item's
    existing note; a present one replaces it (blank or null clears it)."""

    resolution: Optional[Literal["accept", "fix_needed"]]
    note: Optional[str] = Field(default=None, max_length=2000)


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]


class SentenceChange(BaseModel):
    """``text`` is judged by weekly/sentence_edit.plain(), the one place its length and characters are, so the refusal is in our words."""

    action: Literal["edit", "remove", "paragraph"]
    text: Optional[str] = None


class TeamChartBody(BaseModel):
    """``use`` true sets the tool's chart aside for the team's own; false takes that back."""

    use: bool


ReportType = Literal["weekly", "monthly", "quarterly", "half_year", "annual", "companion"]


class DraftRequest(BaseModel):
    """``topic`` is required for Focus of the Week and ``text`` for Company Updates; other sections ignore both.

    ``report_type`` and ``period`` say which report the section belongs to.  The default,
    the weekly report with no period label, is what every draft was before report types.
    """

    # No length here: clean_topic() is the one place a topic's length is judged (resolve_draft calls it),
    # so the API and the pipeline refuse the same topics in the same words.
    topic: Optional[str] = None
    # Focus of the Week: the section titles, one per line. Like the topic, judged by one function (clean_sections).
    sections: Optional[str] = None
    text: Optional[str] = Field(default=None, max_length=10_000)
    report_type: ReportType = WEEKLY
    period: Optional[str] = Field(default=None, max_length=40)
    kind: Optional[str] = Field(default=None, max_length=40)


class SourceBody(BaseModel):
    """One source for one piece of one section.  With no ``text`` and no ``date`` the page at ``url`` is fetched; with them
    the pasted text is kept.  ``sections`` is the Focus's typed titles, which name its pieces."""

    section: str = Field(max_length=40)
    subject: str = Field(max_length=200)
    report_type: ReportType = WEEKLY
    period: Optional[str] = Field(default=None, max_length=40)
    sections: Optional[str] = Field(default=None, max_length=4000)
    url: str = Field(max_length=2000)
    date: Optional[str] = Field(default=None, max_length=20)
    text: Optional[str] = Field(default=None, max_length=1_000_000)   # source_store.from_paste judges the length, in words
    title: Optional[str] = Field(default=None, max_length=300)


class GatherBody(BaseModel):
    """Look again for the sources of one piece (the same gather step a draft runs)."""

    section: str = Field(max_length=40)
    subject: str = Field(max_length=200)
    report_type: ReportType = WEEKLY
    period: Optional[str] = Field(default=None, max_length=40)
    sections: Optional[str] = Field(default=None, max_length=4000)


class InputNotes(BaseModel):
    """What the coordinator types beside the week's files.  A field left out is kept; blank clears it."""

    bidding_range: Optional[str] = Field(default=None, max_length=weekly_inputs.MAX_NOTE)
    previous_issue: Optional[str] = Field(default=None, max_length=weekly_inputs.MAX_NOTE)
    as_at: Optional[str] = Field(default=None, max_length=10)


class ChartLeadIn(BaseModel):
    """The sentence printed above an uploaded chart.  Blank clears it, and the slot's default sentence is printed instead."""

    lead_in: Optional[str] = Field(default=None, max_length=10_000)


class ChartSource(BaseModel):
    """The text printed as "Source: <text>" under an uploaded chart.  Blank clears it, and nothing is printed."""

    source: Optional[str] = Field(default=None, max_length=10_000)


class AnalystInputs(BaseModel):
    """What was typed on the weekly analyst inputs form.  An item left out is kept; null or empty clears it.

    ``fields`` maps a field to its typed value; ``tables`` maps a table to ``{"text": pasted lines}``
    or ``{"rows": [...]}``.  What each may hold is cytonn_weekly/weekly/analyst.py's to judge.
    """

    fields: dict[str, Any] = Field(default_factory=dict)
    tables: dict[str, Any] = Field(default_factory=dict)
    confirm: list[str] = Field(default_factory=list, max_length=60)


class NotableDecision(BaseModel):
    """What the analyst did with one suggestion.  An edit (``edited_headline``) belongs to a selection and a
    ``dismiss_reason`` to a dismissal; the route refuses the other pairings."""

    suggestion_id: str = Field(min_length=1, max_length=64)
    decision: Literal["selected", "dismissed"]
    edited_headline: Optional[str] = None
    dismiss_reason: Optional[Literal["not_relevant", "already_covered", "figures_look_wrong", "other"]] = None


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
    inputs_root: Optional[Union[Path, str]] = None,
    fetch_bulletin: Callable[[date], tuple[bytes, str]] = cbk_bulletin.fetch_bulletin,
    export_root: Optional[Union[Path, str]] = None,
    fetch_usd_rates: Callable[[], dict] = cbk_rates.fetch_usd_rates,
    notable_registry: Optional[Mapping[str, Sequence[Detector]]] = None,
    charts_root: Optional[Union[Path, str]] = None,
    sources_root: Optional[Union[Path, str]] = None,
    fetch_source: Callable[..., source_store.SourceText] = source_store.fetch_page,
    search_sources: source_gather.Search = source_gather.exa_search,
) -> FastAPI:
    """Build the app.  ``db_path`` defaults to data/app.db; tests pass a temp file.

    ``draft_stale_after`` and ``clock`` set when a running draft counts as stuck
    (api/draft_slot.py); tests pass a fake clock instead of waiting an hour.  ``run_keepalive``
    is how often an idle run stream sends its keepalive comment (api/runs.py).

    ``inputs_root`` is where the weekly inputs are kept (default: under the data directory;
    tests pass a temp folder) and ``fetch_bulletin`` how the CBK Weekly Bulletin is fetched
    (tests pass a fake, so none reaches CBK).  ``export_root`` is where exported weekly reports
    are written (default: under the data directory).  ``charts_root`` is where each saved review's chart files are
    kept, ``<run_id>/<chart_id>.png`` and ``.json`` (default: under the data directory; charts/store.py).
    ``sources_root`` is where the sources a Bedrock draft is written from are kept (default: under the data directory;
    common/sources.py) and ``fetch_source`` how one is fetched (tests pass a fake, so none reaches a site).
    ``search_sources`` is how the gather step searches for them (common/gather.py; Exa by default, tests pass a fake).

    ``notable_registry`` is where the "Notable this week" detectors come from (section slug -> detectors).  Left out it is
    the real registry, which is empty: the real app shows no suggestion.  Only a caller that passes one, as the end-to-end
    instance does (e2e/serve_e2e.py), can show any.  There is no environment variable or file that does it.

    ``load_dotenv`` loads the repo-root .env first, before anything here reads os.environ,
    as every entrypoint does: CYTONN_WEB_ORIGINS is read right below, and the pipeline
    reads CYTONN_LLM_PROVIDER and the API keys.  (It used to load in the startup hook,
    after the origins were read, so CYTONN_WEB_ORIGINS only worked from the shell.)
    Library code only reads os.environ.
    """
    if load_dotenv:
        load_env(quiet=True)
        # A key left in a Windows or shell variable beats .env, so editing .env would change nothing: say so once.
        for line in key_override_warnings():
            log.warning(line)
    if configured_provider() == "bedrock":   # outside the .env branch: a container has no .env file, only its variables
        log.warning(bedrock_provider.startup_line())

    database.target(db_path)  # refuses to start when CYTONN_REQUIRE_POSTGRES=1 and there is no PostgreSQL URL (db.py)

    app = FastAPI(title="Cytonn Weekly: coordinator review")
    app.add_exception_handler(ProblemError, problem_handler)
    origins = [o.strip() for o in os.environ.get(CORS_ENV_VAR, DEFAULT_WEB_ORIGINS).split(",") if o.strip()]
    # Content-Disposition is exposed so the web app can read the exported report's file name.
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Disposition"])

    write_lock = threading.Lock()
    draft_slot = DraftSlot(stale_after=draft_stale_after, clock=clock)
    runs = RunRegistry()  # in memory only: a restart forgets every run (api/runs.py)

    # -- helpers ----------------------------------------------------------

    def load(run_id: int) -> CoordinatorReview:
        try:
            return review_store.load_review(run_id, db_path=db_path)
        except KeyError:
            raise ProblemError(404, f"There is no saved review number {run_id}. Go back to the overview and open the section again.", "review_not_found")

    def save(review: CoordinatorReview) -> None:
        new = review.run_id is None
        try:
            review_store.save_review(review, section=section_slug(review), db_path=db_path)
        except review_store.ReviewAlreadyDecided as exc:
            raise ProblemError(409, str(exc), "review_already_decided")
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        if new:
            chart_store.persist(review, charts_root)   # a new review's chart files, under the run id it was just given

    def mutate(run_id: int, change) -> dict:
        """Load, refuse if already decided, apply ``change(review)``, save, return the review."""
        with write_lock:
            review = load(run_id)
            if review.decision is not None:
                raise ProblemError(409, f"This section was already {review.decision} (review {run_id}), so it cannot be changed. "
                                         "Reload the page to see the decision.", "review_already_decided")
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
            raise ProblemError(409, DISCARDED_AS_STUCK, "draft_discarded")
        with write_lock:
            save(review)
        return serialize_review(review)

    def claim_slot(slug: str, report_type: str, period: str) -> Claim:
        """Refuse a draft the provider cannot run (409), then take the one draft slot (409 if another holds it)."""
        problem = provider_problem()
        if problem:
            raise ProblemError(409, problem, "drafting_off")
        title = spec_for(report_type, slug).title
        if report_type != WEEKLY or period:
            title = f"{title} ({report_label(report_type, period)})"
        try:
            claim, replaced = draft_slot.claim(slug, title, report_type, period)
        except DraftBusy as exc:
            raise ProblemError(409, busy_message(exc), "draft_busy")
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
            raise ProblemError(409, f"{spec.title} cannot be drafted yet. {spec.reason}", "draft_section_unavailable")
        topic = body.topic or None
        if spec.needs_topic and not (topic and topic.strip()):
            raise ProblemError(422, f"Type a topic for {spec.title} first, then start the draft.", "draft_topic_missing")
        if topic and topic.strip():
            try:
                topic = clean_topic(topic)  # whitespace-normalized; over focus.review_run.MAX_TOPIC_CHARS is refused
            except ValueError as exc:
                raise ProblemError(422, str(exc), "draft_topic_invalid")
        titles: tuple[str, ...] = ()
        if spec.needs_topic and body.sections and body.sections.strip():
            try:
                titles = tuple(clean_sections(body.sections))   # over MAX_SECTIONS or MAX_SECTION_TITLE is refused, never cut
            except ValueError as exc:
                raise ProblemError(422, str(exc), "draft_input_invalid")
        if spec.needs_topic and not titles and configured_provider() == "bedrock":
            raise ProblemError(409, SECTIONS_REQUIRED, "draft_sections_required")
        if spec.needs_text and not (body.text and body.text.strip()):
            raise ProblemError(422, f"Paste the text for {spec.title} first, then start the draft.", "draft_text_missing")
        ctx = DraftContext(report_type=report_type, period=period, topic=topic, sections=titles, text=body.text, db_path=db_path,
                           week_ending=week_ending_of(period) if report_type == WEEKLY else None, inputs_root=root)
        return spec, ctx, report_type, period

    def find_run(run_id: str) -> Run:
        run = runs.get(run_id)
        if run is None:
            raise ProblemError(404, "This draft run is no longer known: the tool was restarted, and runs are not kept "
                                     "across a restart. Any draft that finished is saved; go back to the overview to find it.", "run_unknown")
        return run

    def work_run(run: Run, spec: SectionSpec, ctx: DraftContext, claim: Optional[Claim]) -> None:
        """The worker thread of one run: the draft route's build, release and save, reported to the run.

        Same builder, same stamp, same save as the draft route, so the review it leaves is the
        same review.  The run is finished only once that review is saved; every other way out
        is ``run_failed`` with the reason.
        """
        run.record(RUN_STARTED, spec.title)
        if claim is not None and configured_provider() == "bedrock":
            gather_for(spec, ctx, run.record)   # never raises: a draft goes ahead with whatever sources are saved
        try:
            review = stamp(spec.build(replace(ctx, on_event=run.record)), ctx.report_type, ctx.period)
        except BaseException as exc:
            if claim is not None:
                draft_slot.release(claim)
            run.fail(failure_message(exc))
            if not isinstance(exc, Exception):
                raise
            log.warning("run %s (%s) failed: %s", run.run_id, spec.slug, safe_describe(exc), exc_info=exc)
            return
        if claim is not None and not draft_slot.release(claim):
            log.warning("draft of %s finished after it was replaced as stuck; its result was discarded", spec.slug)
            run.fail(DISCARDED_AS_STUCK)
            return
        try:
            with write_lock:
                review_store.save_review(review, section=section_slug(review), db_path=db_path)
                chart_store.persist(review, charts_root)
            dev = is_dev_draft(review)
            run.finish(review.run_id, review_counts(review), dev, DEV_MODE_LABEL if dev else None)
        except Exception as exc:  # noqa: BLE001 - the run must end, and say why
            # no traceback for a database error: its message can name the host and the user
            log.warning("run %s (%s) could not save its review: %s", run.run_id, spec.slug, safe_describe(exc),
                        exc_info=not database.is_postgres_error(exc))
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
            "provider_valid": provider in PROVIDERS,
            "dev_mode": provider == "local",
            "dev_mode_label": DEV_MODE_LABEL,
            "spends_api_budget": provider in ("anthropic", "bedrock"),
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
        newest = latest_runs(db_path, report_type, period)
        today = date.today()
        out = []
        for spec in sections_for(report_type, kind):
            latest = None
            run = newest.get(spec.slug)
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
        week = week_ending_of(period) if report_type == WEEKLY else None
        report = {"type": report_type, "title": TYPES[report_type].title, "period": period, "kind": kind,
                  "published_as": TYPES[report_type].published_as,
                  # The weekly report's week: the Friday its period names, and the Friday to suggest.
                  "week_ending": week.isoformat() if week else None,
                  "suggested_week_ending": latest_friday(today).isoformat()}
        # The draft running right now, if any (one at a time across every section and report): it
        # is not saved until it finishes, so without this the overview could not show it at all.
        drafting = draft_slot.status()
        if drafting:  # lets the screen link to the running draft's page; None for a draft the synchronous route runs
            drafting["run_id"] = runs.running_id(drafting["report_type"], drafting["period"], drafting["slug"])
        return {"today": today.isoformat(), "drafting": drafting, "report": report,
                "report_types": report_types(), "companion_kinds": companion_kinds(), "sections": out}

    @app.get("/api/reviews/{run_id}")
    def get_review(run_id: int) -> dict:
        return serialize_review(load(run_id))

    @app.get("/api/reviews/{run_id}/charts/{chart_id}.png")
    def chart_png(run_id: int, chart_id: str) -> Response:
        """A drawn chart's picture, only while it is the file the review recorded (its SHA-256 is checked on every read).

        ``chart_id`` must be a known chart (charts/specs.py), so no other path is ever read.  404 for an unknown
        chart, a review without that drawn chart, or a missing file; 409 when the file has changed since the draft.
        """
        review = load(run_id)
        block = next((b for b in review.section.get("blocks", []) if b.get("kind") == "chart" and b.get("chart_id") == chart_id), None)
        try:
            data = chart_store.read_png(run_id, chart_id, block and block.get("png_sha256"), charts_root)
        except chart_store.ChartFileError as exc:
            raise HTTPException(exc.status, str(exc))
        return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/reviews/{run_id}/charts/{chart_id}/series")
    def chart_series(run_id: int, chart_id: str) -> Response:
        """The series a drawn chart was drawn from (JSON), only while it is the file the review recorded: the same checks
        and answers as the picture (404 unknown chart, no such drawn chart or missing file; 409 for a changed file)."""
        review = load(run_id)
        block = next((b for b in review.section.get("blocks", []) if b.get("kind") == "chart" and b.get("chart_id") == chart_id), None)
        try:
            data = chart_store.read_series(run_id, chart_id, block and block.get("series_sha256"), charts_root)
        except chart_store.ChartFileError as exc:
            raise HTTPException(exc.status, str(exc))
        return Response(data, media_type="application/json", headers={"Cache-Control": "no-store"})

    @app.put("/api/reviews/{run_id}/charts/{chart_id}/team-chart")
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
        return mutate(run_id, change)

    @app.get("/api/reviews/{run_id}/rejected-draft-notes")
    def get_rejected_draft_notes(run_id: int) -> Optional[dict]:
        """The rejected draft just before this run (same section, report and period): its fix-needed items and notes.

        null when the run before was not rejected, held nothing to show, or there is none.  Read-only.
        """
        try:
            previous = review_store.load_previous_review(run_id, db_path=db_path)
        except KeyError:
            raise ProblemError(404, f"There is no saved review number {run_id}. Go back to the overview and open the section again.", "review_not_found")
        return rejected_draft_notes(previous)

    # -- this week's inputs -------------------------------------------------

    root = Path(inputs_root) if inputs_root is not None else None

    def week_of(week_ending: str) -> Week:
        try:
            return Week(date.fromisoformat(week_ending))
        except NotAFriday as exc:
            raise ProblemError(422, str(exc), "week_not_valid")
        except ValueError:
            raise ProblemError(422, f"'{week_ending}' is not a date. Choose the Friday the week ends on.", "week_not_valid")

    def slot_of(slug: str) -> weekly_inputs.Slot:
        slot = weekly_inputs.BY_SLUG.get(slug)
        if slot is None:
            raise HTTPException(404, f"no weekly input {slug!r}")
        return slot

    @app.get("/api/inputs/weekly/{week_ending}")
    def inputs_status(week_ending: str) -> dict:
        """What has been received for the week ending ``week_ending``: per input, the date read from it and whether it fits."""
        return weekly_inputs.status(week_of(week_ending), root)

    @app.put("/api/inputs/weekly/{week_ending}/notes")
    def put_input_notes(week_ending: str, body: InputNotes) -> dict:
        week = week_of(week_ending)
        try:
            weekly_inputs.write_notes(week, {k: getattr(body, k) for k in body.model_fields_set}, root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "note_refused")
        return weekly_inputs.status(week, root)

    def form_section(section: Optional[str]) -> Optional[str]:
        if section is not None and section not in weekly_analyst.WORKBOOKS:
            raise HTTPException(422, f"no weekly analyst inputs for section {section!r}")
        return section

    @app.get("/api/inputs/weekly/{week_ending}/analyst")
    def analyst_inputs(week_ending: str, section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """The weekly analyst inputs form: each item with what was typed, what an uploaded workbook holds, and where they differ."""
        return weekly_analyst.status(week_of(week_ending), root, form_section(section))

    @app.put("/api/inputs/weekly/{week_ending}/analyst")
    def put_analyst_inputs(week_ending: str, body: AnalystInputs,
                           section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Keep what was typed.  422, with every reason (one a line), if any value is refused; nothing is stored then."""
        week, section = week_of(week_ending), form_section(section)
        try:
            weekly_analyst.save_form(week, {"fields": body.fields, "tables": body.tables, "confirm": body.confirm}, root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "analyst_refused")
        return weekly_analyst.status(week, root, section)

    @app.post("/api/inputs/weekly/{week_ending}/analyst/carry")
    def carry_analyst_inputs(week_ending: str, section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Start this week's form from last week's.  409, with the reason, if there is nothing to carry.

        Every carried value is marked with the week it came from; a weekly-changing one is read by
        no draft until it is confirmed (PUT .../analyst with ``confirm``).
        """
        week, section = week_of(week_ending), form_section(section)
        try:
            weekly_analyst.carry_forward(week, root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(409, str(exc), "analyst_nothing_to_carry")
        return weekly_analyst.status(week, root, section)

    @app.post("/api/inputs/weekly/{week_ending}/analyst/suggest/{field}")
    def suggest_analyst_input(week_ending: str, field: str, section: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Work out a suggestion for a running total and keep it, unconfirmed, with its working.  409 if none can be."""
        week, section = week_of(week_ending), form_section(section)
        if field not in weekly_analyst.SUGGESTED_FIELDS:
            raise HTTPException(404, f"no suggestion is worked out for {field!r}")
        from cytonn_weekly.equities.weekly import running_total_suggestions   # imported here: it pulls in the OCR reader

        found = running_total_suggestions(weekly_inputs.WeeklyInputs(week, root), fetch_usd_rates)[field]
        if "reason" in found:
            raise ProblemError(409, found["reason"], "analyst_suggestion_unavailable")
        try:
            weekly_analyst.suggest(week, field, found["value"], found["note"], root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(409, str(exc), "analyst_suggestion_unavailable")
        return weekly_analyst.status(week, root, section)

    def chart_key(key: str) -> str:
        if key not in chart_uploads.KEYS:
            raise HTTPException(404, f"no chart slot {key!r}")
        return key

    @app.put("/api/inputs/weekly/{week_ending}/charts/{key}")
    async def upload_chart(week_ending: str, key: str, request: Request) -> dict:
        """Upload one chart image (PNG or JPEG, judged by its first bytes): the file is the request body.

        It replaces the slot's earlier image. 413 over the size limit, 422 when it is empty or not an image.
        The image is kept for the Word export only; no draft reads it.
        """
        week, key = week_of(week_ending), chart_key(key)
        too_big = (f"The image is over the {chart_uploads.MAX_BYTES // 1_048_576} MB limit. "
                   "Save a smaller copy and upload that.")
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > chart_uploads.MAX_BYTES:
            raise ProblemError(413, too_big, "upload_too_big")
        data = await request.body()
        if len(data) > chart_uploads.MAX_BYTES:
            raise ProblemError(413, too_big, "upload_too_big")
        try:
            await run_in_threadpool(chart_uploads.store, week, key, data, root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "upload_refused")
        return weekly_inputs.status(week, root)

    @app.get("/api/inputs/weekly/{week_ending}/charts/{key}/image")
    def chart_upload_image(week_ending: str, key: str) -> Response:
        week, key = week_of(week_ending), chart_key(key)
        stored = chart_uploads.image(week, key, root)
        if stored is None:
            raise HTTPException(404, "this chart has no image")
        return Response(stored[0], media_type=chart_uploads.MEDIA_TYPE[stored[1]], headers={"Cache-Control": "no-store"})

    @app.delete("/api/inputs/weekly/{week_ending}/charts/{key}")
    def delete_chart(week_ending: str, key: str) -> dict:
        week, key = week_of(week_ending), chart_key(key)
        if not chart_uploads.remove(week, key, root):
            raise HTTPException(404, "this chart has no image")
        return weekly_inputs.status(week, root)

    @app.put("/api/inputs/weekly/{week_ending}/charts/{key}/lead-in")
    def put_chart_lead_in(week_ending: str, key: str, body: ChartLeadIn) -> dict:
        week, key = week_of(week_ending), chart_key(key)
        try:
            chart_uploads.set_lead_in(week, key, body.lead_in, root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "note_refused")
        return weekly_inputs.status(week, root)

    @app.put("/api/inputs/weekly/{week_ending}/charts/{key}/source")
    def put_chart_source(week_ending: str, key: str, body: ChartSource) -> dict:
        week, key = week_of(week_ending), chart_key(key)
        try:
            chart_uploads.set_source(week, key, body.source, root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "note_refused")
        return weekly_inputs.status(week, root)

    @app.put("/api/inputs/weekly/{week_ending}/{slot}")
    async def upload_input(week_ending: str, slot: str, request: Request,
                           filename: str = Query(default="", max_length=260)) -> dict:
        """Upload one input: the file is the request body.  It is checked and read before it is kept.

        413 if it is over the size limit, 422 (with the reason) if it is not the document the
        slot takes, or is a KCB daily report for a day outside the week.
        """
        week, spec = week_of(week_ending), slot_of(slot)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > weekly_inputs.MAX_BYTES:
            raise ProblemError(413, f"{spec.title}: the file is over the {weekly_inputs.MAX_BYTES // 1_048_576} MB limit. "
                                     "Upload a smaller copy of the file.", "upload_too_big")
        data = await request.body()
        if len(data) > weekly_inputs.MAX_BYTES:
            raise ProblemError(413, f"{spec.title}: the file is over the {weekly_inputs.MAX_BYTES // 1_048_576} MB limit. "
                                     "Upload a smaller copy of the file.", "upload_too_big")
        try:
            await run_in_threadpool(weekly_inputs.store, week, slot, data, filename, root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "upload_refused")
        return weekly_inputs.status(week, root)

    @app.post("/api/inputs/weekly/{week_ending}/cbk_bulletin/fetch")
    def fetch_bulletin_input(week_ending: str) -> dict:
        """Fetch the week's CBK Weekly Bulletin from centralbank.go.ke and keep it as an input."""
        week = week_of(week_ending)
        try:
            data, url = fetch_bulletin(week.ending)
        except LookupError as exc:
            raise ProblemError(404, f"{exc}. CBK may not have published it yet: try again later, or upload the PDF yourself.", "bulletin_not_published")
        except Exception as exc:  # noqa: BLE001 - shown to the coordinator, not swallowed
            raise ProblemError(502, f"The bulletin could not be fetched from CBK. {failure_message(exc)} You can also upload "
                                     "the PDF yourself.", "bulletin_fetch_failed")
        try:
            weekly_inputs.store(week, weekly_inputs.CBK_BULLETIN, data, url.rsplit("/", 1)[-1], root, fetched_from=url)
        except weekly_inputs.InputError as exc:
            raise ProblemError(502, f"CBK's file was downloaded but could not be read as the Weekly Bulletin ({exc}). Upload "
                                     "the bulletin yourself.", "bulletin_fetch_failed")
        return weekly_inputs.status(week, root)

    # -- Notable this week: suggestions for the analyst, and the analyst's decisions on them ---------------
    # Nothing here reads or writes a review, an approval, the analyst form or the export (cytonn_weekly/notable/).

    detectors = notable.REGISTRY if notable_registry is None else notable_registry

    def notable_section(slug: str) -> None:
        if spec_for(WEEKLY, slug) is None:
            raise HTTPException(404, f"no section {slug!r} in the weekly report")

    def notable_state(slug: str, week: Optional[Week]) -> dict:
        """The section's suggestions for the week, each with the analyst's decision on it (or null)."""
        if week is None:  # a report that is not the weekly one: nothing is computed for it yet
            return {"section": slug, "week_ending": None, "suggestions": [], "failed_checks": 0}
        found, failed = run_detectors(detectors, slug, DetectorContext(week.ending))
        decided = notable_store.load(db_path, week.ending.isoformat(), slug)
        return {"section": slug, "week_ending": week.ending.isoformat(), "failed_checks": failed,
                "suggestions": [{**s.to_dict(), "decision": decided.get(s.id)} for s in found]}

    @app.get("/api/notable/{section}")
    def notable_get(section: str, week_ending: Optional[str] = Query(default=None, max_length=10),
                    report_type: ReportType = Query(default=WEEKLY)) -> dict:
        """The suggestions for one section of one week, highest rank first.  Only the weekly report has any, for now."""
        notable_section(section)
        if report_type != WEEKLY:
            return notable_state(section, None)
        if week_ending is None:
            raise HTTPException(422, "the weekly report's suggestions need week_ending, the Friday the week ends on (2026-10-02)")
        return notable_state(section, week_of(week_ending))

    @app.post("/api/notable/{section}/decisions")
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
        notable_store.save(db_path, week.ending.isoformat(), section, body.suggestion_id, body.decision,
                           None if edited == current["headline"] else edited, body.dismiss_reason)
        return notable_state(section, week)

    @app.delete("/api/notable/{section}/decisions/{suggestion_id}")
    def notable_restore(section: str, suggestion_id: str, week_ending: str = Query(max_length=10)) -> dict:
        """Take the decision back: the suggestion is open again.  404 if there was none."""
        notable_section(section)
        week = week_of(week_ending)
        if not notable_store.delete(db_path, week.ending.isoformat(), section, suggestion_id):
            raise HTTPException(404, f"no saved decision for suggestion {suggestion_id!r} in the week ending {week.ending.isoformat()}")
        return notable_state(section, week)

    # -- export: the approved weekly report as one Word file ---------------------

    def weekly_period(period: Optional[str]) -> str:
        try:
            return normalize_period(WEEKLY, period)
        except PeriodError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/export/weekly")
    def export_weekly_status(period: Optional[str] = Query(default=None, max_length=40)) -> dict:
        """Whether the week's report can be exported: every weekly section's state, and whether it is a dev-mode draft."""
        return weekly_export.export_status(db_path, weekly_period(period), inputs_root=root)

    @app.get("/api/previous/weekly")
    def previous_weekly() -> dict:
        """Every fully approved weekly week, newest first, the week after the latest of them, and the week the overview opens on."""
        return weekly_export.approved_weeks(db_path)

    @app.post("/api/export/weekly")
    def export_weekly(period: Optional[str] = Query(default=None, max_length=40)) -> FileResponse:
        """Write the approved weekly report and return the .docx.  409, naming each section, unless all are approved.

        Nothing is sent or published: the file is handed to the coordinator who asked for it.  A dev-mode
        draft is exported with its watermark and banner.
        """
        normalized = weekly_period(period)
        try:
            path = weekly_export.write_weekly_report(db_path, normalized, export_root, charts_root=charts_root,
                                                     inputs_root=root)
        except weekly_export.ExportNotAllowed as exc:
            raise ProblemError(409, str(exc), "export_not_ready")
        return FileResponse(path, filename=path.name,
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.delete("/api/inputs/weekly/{week_ending}/{stored_name}")
    def delete_input(week_ending: str, stored_name: str) -> dict:
        week = week_of(week_ending)
        if not weekly_inputs.remove(week, stored_name, root):
            raise HTTPException(404, f"no stored input {stored_name!r} for the week ending {week.ending.isoformat()}")
        return weekly_inputs.status(week, root)


    # -- the sources a Bedrock draft is written from --------------------------

    sources_dir = Path(sources_root) if sources_root is not None else None

    def refuse_while_drafting() -> None:
        """A draft reads the saved sources as it goes, so none may change under it.  The slot is one draft at a time across
        every section, so this refuses while any draft holds it (a stuck one, past the stale limit, does not count).
        ponytail: not narrowed to the section being drafted; do that if a long draft of another section gets in the way."""
        held = draft_slot.status()
        if held and not held["stale"]:
            raise HTTPException(409, f"{held['title']} is being drafted right now, so sources cannot be added or removed until "
                                     "it finishes. Wait for it, then try again.")

    def source_piece(section: str, subject: str, report_type: str, period: Optional[str], typed: Optional[str]):
        """(the section's spec, the normalized period, the piece) a source is for, or a plain refusal (404, 422)."""
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
                "week_end": latest_friday(piece.end).isoformat(), "sources": [s.meta() for s in items]}

    @app.get("/api/sources")
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
            pieces = [source_meta(p, source_store.list_for(p.subject, p.end, sources_dir)) for p in found]
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        return {"section": section, "title": spec.title, "uses_sources": True, "pieces": pieces,
                "approved_sites": list(source_store.APPROVED_SITES)}

    @app.post("/api/sources")
    def add_source(body: SourceBody) -> dict:
        """Keep one source for a piece: with no ``text`` and no ``date`` the page at ``url`` is fetched (any site; the safety rules of common/sources.py apply);
        with them, the pasted text is kept as it is, under the address and date given.  422 with the reason if it is refused."""
        spec, period, piece = source_piece(body.section, body.subject, body.report_type, body.period, body.sections)
        refuse_while_drafting()
        pasted = bool((body.text or "").strip() or (body.date or "").strip())
        try:
            if pasted:
                added = source_store.from_paste(body.url, body.date or "", body.text or "", piece.subject, piece.end,
                                                title=body.title or "", root=sources_dir)
            else:
                added = fetch_source(body.url, piece.subject, piece.end, root=sources_dir)
            items = source_store.list_for(piece.subject, piece.end, sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(422, str(exc))
        return {"source": added.meta(), **source_meta(piece, items)}

    @app.get("/api/sources/{source_id}")
    def source_facts(source_id: str) -> dict:
        """One saved source's facts: what the list route returns for it, without the text (that is /text)."""
        try:
            src = source_store.get(source_id, sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        if src is None:
            raise HTTPException(404, f"no saved source {source_id!r}")
        return src.meta()

    @app.get("/api/sources/{source_id}/text")
    def source_text(source_id: str) -> Response:
        """The saved text of one source, as plain text: what the model was shown and what its quotes are checked against."""
        try:
            src = source_store.get(source_id, sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        if src is None:
            raise HTTPException(404, f"no saved source {source_id!r}")
        return Response(src.text, media_type="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.delete("/api/sources/{source_id}")
    def delete_source(source_id: str) -> dict:
        refuse_while_drafting()
        try:
            gone = source_store.get(source_id, sources_dir)
        except source_store.SourceError:
            gone = None
        if not source_store.remove(source_id, sources_dir):
            raise HTTPException(404, f"no saved source {source_id!r}")
        if gone:   # the first look after a removal is not held back by the cooldown
            gather_stamps.pop((gone.week_end, source_store.subject_key(gone.subject)), None)
        return {"removed": source_id}

    gather_stamps: dict[tuple[str, str], float] = {}   # (Friday, piece) -> when it was last looked for, in memory only
    gather_cooldown = 3600.0

    def gather_for(spec: SectionSpec, ctx: DraftContext, on_event: Callable[..., object]) -> None:
        """The gather step at the start of a Bedrock run: search for the sources of each piece of the section."""
        try:
            pieces = pieces_for(ctx.report_type, ctx.period, spec.slug, sections=ctx.sections, today=date.today()) or []
            _, looked = source_gather.gather(pieces, search=search_sources, fetch=fetch_source, root=sources_dir, on_event=on_event)
            for p in pieces if looked else []:
                gather_stamps[(latest_friday(p.end).isoformat(), source_store.subject_key(p.subject))] = clock()
        except Exception as exc:  # noqa: BLE001 - gathering never fails a draft
            log.warning("gathering sources for %s was skipped: %s", spec.slug, type(exc).__name__)

    @app.post("/api/sources/gather")
    def gather_sources(body: GatherBody) -> dict:
        """Run the gather step for one piece. 409 while a draft holds the slot. Once an hour per piece, except the first
        look after a source is removed. Answers with what was saved, how many, and the piece's sources."""
        _, _, piece = source_piece(body.section, body.subject, body.report_type, body.period, body.sections)
        refuse_while_drafting()
        key = (latest_friday(piece.end).isoformat(), source_store.subject_key(piece.subject))
        limits = source_gather.limits_from_env()
        reason, saved = None, []
        try:
            have = source_store.list_for(piece.subject, piece.end, sources_dir)
            last = gather_stamps.get(key)
            if len(have) >= limits.enough:
                reason = f"This piece already has {len(have)} sources, so none were looked for."
            elif last is not None and clock() - last < gather_cooldown:
                reason = "Sources were looked for less than an hour ago. Add one by hand, or look again later."
            else:
                saved, looked = source_gather.gather([piece], search=search_sources, fetch=fetch_source, root=sources_dir,
                                                     limits=limits)
                if looked:
                    gather_stamps[key] = clock()
                else:
                    reason = source_gather.NOT_CONFIGURED
            items = source_store.list_for(piece.subject, piece.end, sources_dir)
        except source_store.SourceError as exc:
            raise HTTPException(409, str(exc))
        return {"found": len(saved), "reason": reason, "added": [s.meta() for s in saved], **source_meta(piece, items)}

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
                raise ProblemError(502, f"The draft stopped. {failure_message(exc)}", "draft_failed")

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
                raise ProblemError(409, str(exc), "draft_sections_not_approved")
            except ValueError as exc:  # e.g. an unusable Focus topic, or missing Company Updates text
                raise ProblemError(422, str(exc), "draft_input_invalid")
            except Exception as exc:  # noqa: BLE001 - shown to the coordinator, not swallowed
                raise ProblemError(502, f"The draft stopped. {failure_message(exc)}", "draft_failed")

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
            raise ProblemError(
                409,
                "The tool's drafting mode changed after this page was opened. Reload the page to see what a draft "
                "will use, then start it again.",
                "draft_mode_changed")
        try:
            run = runs.start(report_type, period, spec.slug, spec.title, TYPES[report_type].title, clock())
        except RunAlreadyRunning:
            raise ProblemError(
                409,
                f"{spec.title}{f' for {period}' if period else ''} is already being drafted. It is saved when it "
                "finishes, and the overview shows it until then. Wait for it, then open it from the overview.",
                "draft_already_running")
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
        run = find_run(run_id)
        out = run.to_dict()
        if run.status == RUNNING:  # the server's count, so a screen that opens late or reloads still shows the true time
            out["elapsed_seconds"] = max(0, int(clock() - run.started_at))
            out["stale"] = out["elapsed_seconds"] >= draft_stale_after
        return out

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

    @app.post("/api/reviews/{run_id}/items/{index}/fix-input")
    async def fix_from_input(run_id: int, index: int, request: Request, slot: str = Query(max_length=40),
                             filename: str = Query(default="", max_length=260)) -> dict:
        """Re-check a flagged item against a file the reviewer uploads (the file is the request body, as for an input upload).

        The file is checked and the section's figures re-read on a copy of the week's inputs, with no network and no model
        (weekly/recheck.py).  Only if that works is the file kept and a NEW undecided review saved; the earlier review is
        never edited.  Answers ``{"review", "result"}``.  The draft slot and the run registry are not touched.
        """
        old = load(run_id)
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
            done = await run_in_threadpool(weekly_recheck.recheck, old, slot, data, filename, root, charts_root)
        except weekly_inputs.InputError as exc:
            raise ProblemError(422, str(exc), "fix_file_refused")
        except Exception as exc:  # noqa: BLE001 - shown to the reviewer; nothing was kept or saved
            log.exception("re-check of run %s from %s failed", run_id, slot)
            raise ProblemError(500, f"The figures could not be re-checked, so nothing was changed and the file was not kept. {failure_message(exc)}", "fix_check_failed")
        with write_lock:
            try:
                weekly_inputs.store(week, slot, data, filename, root)
            except weekly_inputs.InputError as exc:
                raise ProblemError(422, str(exc), "fix_file_refused")
            try:
                save(done.review)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("saving the re-checked review of run %s failed", run_id)
                raise ProblemError(500, "The file was kept among this week's inputs, but the new version could not be saved. "
                                        f"Try again. {failure_message(exc)}", "fix_check_failed")
        return {"review": serialize_review(done.review),
                "result": {"changes": done.changes, "changed_items": done.changed_items, "kept": done.kept,
                           "earlier_run_id": run_id, "slot": slot, "was_approved": old.decision == "approved"}}

    @app.post("/api/reviews/{run_id}/items/{index}/sentence")
    def change_sentence(run_id: int, index: int, body: SentenceChange) -> dict:
        """Rewrite or remove one flagged sentence of a drafted piece by hand: no model, no network.

        The figures are checked again with the same offline checker, and a NEW undecided review is saved (the earlier
        one is never edited, even if approved).  Answers ``{"review", "result"}``.  The draft slot and runs are not touched.
        """
        old = load(run_id)
        try:
            if body.action == "paragraph":   # a whole carried-forward paragraph, retyped by hand
                done = sentence_edit.apply_paragraph(old, index, body.text, charts_root)
            else:
                done = sentence_edit.apply(old, index, body.action, body.text, charts_root)
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
        with write_lock:
            try:
                save(done.review)
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001
                log.exception("saving the %s of a sentence in run %s failed", body.action, run_id)
                raise ProblemError(500, sentence_edit.SAVE_FAILED, "edit_save_failed")
        return {"review": serialize_review(done.review),
                "result": {"action": done.action, "changed_items": done.changed_items, "earlier_run_id": run_id,
                           "was_approved": old.decision == "approved"}}

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
                raise ProblemError(409, str(exc), "review_not_decidable")
            save(review)
            return serialize_review(review)

    app.router.on_shutdown.append(database.close_all)  # the held PostgreSQL connection, if any
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
