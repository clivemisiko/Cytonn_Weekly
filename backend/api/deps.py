import logging
import os
import threading
from collections import deque
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional
from fastapi import HTTPException
from cytonn_weekly.charts import store as chart_store
from cytonn_weekly.common import gather as source_gather
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.common.run_events import RUN_STARTED, current_observer, describe, frames, redact, review_counts, safe_describe, user_message
from cytonn_weekly.digital_payments import review_store
from cytonn_weekly.digital_payments.coordinator_review import CoordinatorReview
from cytonn_weekly.digital_payments.provider_factory import ENV_VAR as PROVIDER_ENV_VAR
from cytonn_weekly.digital_payments.provider_factory import ANTHROPIC_REMOVED, NOT_CONFIGURED
from cytonn_weekly.digital_payments.providers.local_provider import EXA_KEY_ENV_VAR, EXA_KEY_MISSING, SearchKeyError
from cytonn_weekly.focus.review_run import clean_sections, clean_topic
from cytonn_weekly import db as database
from cytonn_weekly import notable
from cytonn_weekly.narrative import bedrock_provider
from cytonn_weekly.narrative.base import NothingDrafted
from cytonn_weekly.report_sections import DraftContext, SectionSpec, companion_kinds, section_slug, spec_for
from cytonn_weekly.source_pieces import pieces_for
from cytonn_weekly.report_types import COMPANION, TYPES, WEEKLY, PeriodError, normalize_period, week_ending_of
from cytonn_weekly.weekly.week import NotAFriday, Week, latest_friday
from api.problems import ProblemError
from api.draft_slot import Claim, DraftBusy, DraftSlot, busy_message, draft_concurrency, draft_queue_max
from api.runs import ACTIVE, RUNNING, Run, RunRegistry
from cytonn_weekly.run_store import RunStore
from api.serialize import DEV_MODE_LABEL, is_dev_draft, serialize_review
from api.schemas import DraftRequest

log = logging.getLogger(__name__)

DISCARDED_AS_STUCK = (
    "This draft ran so long that it was treated as stuck, and a newer draft replaced it. Its result was not saved. "
    "Open the section to see the newer draft."
)

PROVIDERS = ("bedrock", "local")
SECTIONS_REQUIRED = (
    "With Amazon Bedrock the model searches nothing, so it cannot propose the section titles from the topic alone. Type "
    "the section titles for this Focus (one a line, up to 8), supply the pages to read for each, then start the draft.")


NOT_CONFIGURED_LABEL = "not configured"


def configured_provider() -> str:
    """The provider the server was told to use; "" when the variable is unset or blank."""
    return (os.environ.get(PROVIDER_ENV_VAR) or "").strip().lower()


def provider_label() -> str:
    """What the screen shows and sends back as the provider: the name, or "not configured"."""
    return configured_provider() or NOT_CONFIGURED_LABEL


def failure_message(exc: BaseException) -> str:
    """Why a run stopped, as one line for the screen: the error's own message, no traceback, no secrets.

    A ValueError is the pipeline talking to the analyst (an unusable topic, sections not
    yet approved), so its message stands alone, as the draft route shows it; so is a
    SearchKeyError (the web-search key is missing or was refused).  Anything else is named
    by its type.  Any configured secret that an error message happens to quote is removed
    before it is recorded.
    """
    if isinstance(exc, (ValueError, SearchKeyError, bedrock_provider.BedrockError, NothingDrafted)):
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

    Checked before a draft claims the slot or fetches anything: without it, a draft with no
    credentials would fetch every source first and then fail inside the SDK.
    Local mode is checked the same way for its web-search key: every section but Digital
    Payments searches afresh each draft, and Digital Payments' cache lasts one day.  Only
    a missing key is known here; a key Exa refuses is reported by the search itself.
    """
    provider = configured_provider()
    if not provider:
        return NOT_CONFIGURED
    if provider == "anthropic":
        return ANTHROPIC_REMOVED
    if provider not in PROVIDERS:
        return f"Unknown {PROVIDER_ENV_VAR} value {provider!r}; expected 'bedrock' or 'local'."
    if provider == "bedrock":
        return bedrock_provider.env_problem()
    if provider == "local" and not (os.environ.get(EXA_KEY_ENV_VAR) or "").strip():
        return EXA_KEY_MISSING
    return None



def uses_provider(spec: SectionSpec) -> bool:
    """Whether drafting the section calls the LLM provider (the Executive Summary never does)."""
    return not spec.requires_approved


def report_label(report_type: str, period: str) -> str:
    return period or TYPES[report_type].title


def chosen_report(report_type: str, period: Optional[str], kind: Optional[str]) -> tuple[str, Optional[str]]:
    """The normalized period (422 if it does not fit the type) and the companion kind (422 if unknown)."""
    try:
        normalized = normalize_period(report_type, period)
    except PeriodError as exc:
        raise HTTPException(422, str(exc))
    if report_type == COMPANION and kind is not None and kind not in {k["slug"] for k in companion_kinds()}:
        raise HTTPException(422, f"unknown companion report kind {kind!r}")
    return normalized, kind


def week_of(week_ending: str) -> Week:
    try:
        return Week(date.fromisoformat(week_ending))
    except NotAFriday as exc:
        raise ProblemError(422, str(exc), "week_not_valid")
    except ValueError:
        raise ProblemError(422, f"'{week_ending}' is not a date. Choose the Friday the week ends on.", "week_not_valid")


class Deps:
    """The state one app shares between its routers: the review store, the drafting seats and queue, the run registry, the
    roots the weekly inputs, sources, snips, charts and exports are kept under, and the injected fetchers (create_app builds it)."""

    def __init__(self, db_path, *, draft_stale_after, clock, run_keepalive, inputs_root, fetch_bulletin, export_root,
                 fetch_usd_rates, notable_registry, charts_root, sources_root, fetch_source, search_sources):
        self.db_path = db_path
        self.draft_stale_after = draft_stale_after
        self.clock = clock
        self.run_keepalive = run_keepalive
        self.fetch_bulletin = fetch_bulletin
        self.export_root = export_root
        self.fetch_usd_rates = fetch_usd_rates
        self.charts_root = charts_root
        self.fetch_source = fetch_source
        self.search_sources = search_sources
        self.write_lock = threading.Lock()
        self.draft_slot = DraftSlot(capacity=draft_concurrency(), stale_after=draft_stale_after, clock=clock)
        self.run_store = RunStore(db_path)
        self.runs = RunRegistry(store=self.run_store)  # live runs stream from memory; every change is also written through (api/runs.py)
        self.queue_max = draft_queue_max()
        self.waiting: deque[tuple[Run, SectionSpec, DraftContext]] = deque()   # runs waiting for a seat, first in first out
        self.seats = threading.Lock()   # "take a seat or join the queue" and "free a seat, start the next" are each one step
        self.root = Path(inputs_root) if inputs_root is not None else None
        self.sources_dir = Path(sources_root) if sources_root is not None else None
        self.snips_dir = Path(sources_root).parent / "snips" if sources_root is not None else None
        self.detectors = notable.REGISTRY if notable_registry is None else notable_registry
        self.gather_stamps: dict[tuple[str, str], float] = {}   # (Friday, piece) -> when it was last looked for, in memory only
        self.gather_cooldown = 3600.0

    def load(self, run_id: int) -> CoordinatorReview:
        try:
            return review_store.load_review(run_id, db_path=self.db_path)
        except KeyError:
            raise ProblemError(404, f"There is no saved review number {run_id}. Go back to the overview and open the section again.", "review_not_found")

    def save(self, review: CoordinatorReview) -> None:
        new = review.run_id is None
        try:
            review_store.save_review(review, section=section_slug(review), db_path=self.db_path)
        except review_store.ReviewAlreadyDecided as exc:
            raise ProblemError(409, str(exc), "review_already_decided")
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        if new:
            chart_store.persist(review, self.charts_root)   # a new review's chart files, under the run id it was just given

    def mutate(self, run_id: int, change) -> dict:
        """Load, refuse if already decided, apply ``change(review)``, save, return the review."""
        with self.write_lock:
            review = self.load(run_id)
            if review.decision is not None:
                raise ProblemError(409, f"This section was already {review.decision} (review {run_id}), so it cannot be changed. "
                                         "Reload the page to see the decision.", "review_already_decided")
            change(review)
            self.save(review)
            return serialize_review(review)

    def stamp(self, review: CoordinatorReview, report_type: str, period: str) -> CoordinatorReview:
        """Set the review's key before its first save (a weekly build knows nothing of report types)."""
        review.report_type, review.period = report_type, period
        return review

    def build_tracked(self, spec: Any, ctx: Any, report_type: str, period: str) -> CoordinatorReview:
        """The section's build, with the draft's Bedrock calls and tokens counted (and capped) as one, and saved as ``usage``."""
        with bedrock_provider.track_usage() as used:
            review = self.stamp(spec.build(ctx), report_type, period)
        if used.calls:
            review.section["usage"] = bedrock_provider.usage_record(used, bedrock_provider.model_id())
        return review

    def run_quick(self, build: Callable[[], CoordinatorReview]) -> dict:
        """A section that neither searches nor calls the LLM (the Executive Summary).

        It takes no draft slot: it finishes at once and spends nothing, so a long draft of
        another section must not hold it up.
        """
        review = build()
        with self.write_lock:
            self.save(review)
        return serialize_review(review)

    def run_draft(self, slug: str, build: Callable[[], CoordinatorReview], report_type: str = WEEKLY,
                  period: str = "") -> dict:
        """Take a drafting seat, run ``build``, save the result at once, and free the seat.

        A fresh draft is saved before it is returned, so a closed tab never loses a paid run.
        The one exception is a run that held the slot so long it was taken over as stuck: its
        result is discarded (see api/draft_slot.py), because saving it would put an abandoned
        run over the newer draft that replaced it.
        """
        claim = self.claim_slot(slug, report_type, period)
        try:
            review = build()
        except BaseException:
            self.free_seat(claim)
            raise
        if not self.free_seat(claim):
            log.warning("draft of %s finished after it was replaced as stuck; its result was discarded", slug)
            raise ProblemError(409, DISCARDED_AS_STUCK, "draft_discarded")
        with self.write_lock:
            self.save(review)
        return serialize_review(review)

    def take_seat(self, slug: str, report_type: str, period: str) -> Claim:
        """Take a drafting seat or raise DraftBusy; a seat held past the stale limit is taken over."""
        title = spec_for(report_type, slug).title
        if report_type != WEEKLY or period:
            title = f"{title} ({report_label(report_type, period)})"
        claim, replaced = self.draft_slot.claim(slug, title, report_type, period)
        if replaced is not None:
            log.warning("draft of %s (started %.0fs ago) was treated as stuck and replaced by a draft of %s",
                        replaced.slug, claim.started_at - replaced.started_at, slug)
        return claim

    def claim_slot(self, slug: str, report_type: str, period: str) -> Claim:
        """The synchronous draft routes: refuse a draft the provider cannot run (409), then take a seat (409 if all are taken;
        only a run, started with POST /api/runs, waits in the queue)."""
        problem = provider_problem()
        if problem:
            raise ProblemError(409, problem, "drafting_off")
        try:
            return self.take_seat(slug, report_type, period)
        except DraftBusy as exc:
            raise ProblemError(409, busy_message(exc), "draft_busy")

    def free_seat(self, claim: Claim) -> bool:
        """Give a seat back and start the next queued run.  False means the seat had been taken over as stale."""
        released = self.draft_slot.release(claim)
        self.start_next()
        return released

    def start_next(self) -> None:
        """A seat is free: start queued runs, oldest first, while seats last."""
        while True:
            with self.seats:
                if not self.waiting:
                    return
                run, spec, ctx = self.waiting[0]
                try:
                    claim = self.take_seat(spec.slug, ctx.report_type, ctx.period)
                except DraftBusy:
                    return
                self.waiting.popleft()
                run.begin(self.clock())
            self.launch(run, spec, ctx, claim)

    def launch(self, run: Run, spec: SectionSpec, ctx: DraftContext, claim: Optional[Claim]) -> None:
        threading.Thread(target=self.guarded_run, args=(run, spec, ctx, claim), name=f"run-{run.run_id[:8]}", daemon=True).start()

    def guarded_run(self, run: Run, spec: SectionSpec, ctx: DraftContext, claim: Optional[Claim]) -> None:
        """One run's thread: whatever happens in it ends this run only, and its seat always goes back."""
        try:
            self.work_run(run, spec, ctx, claim)
        except Exception as exc:  # noqa: BLE001 - work_run reports the failures it foresees; this is the rest
            log.warning("run %s (%s) stopped unexpectedly: %s", run.run_id, spec.slug, safe_describe(exc))
            if run.status in ACTIVE:
                run.fail("The draft stopped unexpectedly. See the server log.")
        finally:
            if claim is not None:
                self.free_seat(claim)   # a no-op when work_run already gave the seat back (before it saved)

    def queue_position(self, run: Run) -> Optional[int]:
        """1 for the run next in line, or None when it is not waiting."""
        with self.seats:
            return next((i + 1 for i, (r, _, _) in enumerate(self.waiting) if r is run), None)

    def resolve_draft(self, slug: str, body: DraftRequest) -> tuple[SectionSpec, DraftContext, str, str]:
        """Validate one draft request: (the section's spec, its draft context, the report type, the normalized period).

        Both ways of starting a draft (the synchronous route and a run) go through this, so
        they refuse the same things with the same words: a period that does not fit the type
        (422), an unknown section (404), an unavailable one (409), a missing topic (422).
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
        ctx = DraftContext(report_type=report_type, period=period, topic=topic, sections=titles, db_path=self.db_path,
                           week_ending=week_ending_of(period) if report_type == WEEKLY else None, inputs_root=self.root)
        return spec, ctx, report_type, period

    def find_run(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise ProblemError(404, "This draft run is no longer known: the tool was restarted, and runs are not kept "
                                     "across a restart. Any draft that finished is saved; go back to the overview to find it.", "run_unknown")
        return run

    def work_run(self, run: Run, spec: SectionSpec, ctx: DraftContext, claim: Optional[Claim]) -> None:
        """The worker thread of one run: the draft route's build, release and save, reported to the run.

        Same builder, same stamp, same save as the draft route, so the review it leaves is the
        same review.  The run is finished only once that review is saved; every other way out
        is ``run_failed`` with the reason.
        """
        run.record(RUN_STARTED, spec.title)
        current_observer.set(run.record)   # this thread's draft: a provider that waits and retries reports it here
        if claim is not None and configured_provider() == "bedrock":
            self.gather_for(spec, ctx, run.record)   # never raises: a draft goes ahead with whatever sources are saved
        try:
            review = self.build_tracked(spec, replace(ctx, on_event=run.record), ctx.report_type, ctx.period)
        except BaseException as exc:
            if claim is not None:
                self.free_seat(claim)
            if isinstance(exc, Exception):   # logged first: once the run says "failed" a reader may look for the line at once
                log.warning("run %s (%s) failed: %s; %s", run.run_id, spec.slug, safe_describe(exc), frames(exc))
            run.fail(failure_message(exc))
            if not isinstance(exc, Exception):
                raise
            return
        if claim is not None and not self.free_seat(claim):   # the seat goes back before the save, so the next run starts at once
            log.warning("draft of %s finished after it was replaced as stuck; its result was discarded", spec.slug)
            run.fail(DISCARDED_AS_STUCK)
            return
        try:
            with self.write_lock:
                review_store.save_review(review, section=section_slug(review), db_path=self.db_path)
                chart_store.persist(review, self.charts_root)
            if review.section.get("usage"):
                run.record_usage(review.section["usage"])
            dev = is_dev_draft(review)
            run.finish(review.run_id, review_counts(review), dev, DEV_MODE_LABEL if dev else None)
        except Exception as exc:  # noqa: BLE001 - the run must end, and say why
            # no traceback for a database error: its message can name the host and the user
            log.warning("run %s (%s) could not save its review: %s", run.run_id, spec.slug, safe_describe(exc),
                        exc_info=not database.is_postgres_error(exc))
            run.fail(failure_message(exc))

    def refuse_while_drafting(self, subject: str, friday: str) -> None:
        """A draft reads the saved sources of its own pieces as it goes, so none of those may change under it.  Refuses only
        while a draft that reads this piece (``subject`` filed under ``friday``) is running or queued; a draft of any other
        section is no reason to wait.  A running draft past the stale limit is treated as stuck and does not hold anything."""
        key = (source_store.subject_key(subject), friday)
        for run in self.runs.active():
            if run.status == RUNNING and self.clock() - run.started_at >= self.draft_stale_after:
                continue
            if key in run.piece_keys:
                raise HTTPException(409, f"{run.section_title} is being drafted or is queued, and it reads this piece's sources, so "
                                         "they cannot be added or removed until it finishes. Wait for it, then try again.")

    def gather_for(self, spec: SectionSpec, ctx: DraftContext, on_event: Callable[..., object]) -> None:
        """The gather step at the start of a Bedrock run: search for the sources of each piece of the section."""
        if spec.slug == "real_estate" and ctx.report_type == WEEKLY:
            return   # the weekly Real Estate is written from the analyst's snips alone: nothing is searched for it
        try:
            pieces = pieces_for(ctx.report_type, ctx.period, spec.slug, sections=ctx.sections, today=date.today()) or []
            _, looked = source_gather.gather(pieces, search=self.search_sources, fetch=self.fetch_source, root=self.sources_dir, on_event=on_event,
                                            limits=source_gather.limits_from_env(spec.slug))
            for p in pieces if looked else []:
                self.gather_stamps[(latest_friday(p.end).isoformat(), source_store.subject_key(p.subject))] = self.clock()
        except Exception as exc:  # noqa: BLE001 - gathering never fails a draft
            log.warning("gathering sources for %s was skipped: %s", spec.slug, type(exc).__name__)
