"""FastAPI app for the analyst review of every report section.

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
stream from memory and are also saved as they happen (api/runs.py, run_store.py).  The synchronous draft routes above are unchanged.

/api/inputs/weekly/{week_ending} is "This week's inputs": the files an analyst uploads
for one report week (cytonn_weekly/weekly/inputs.py).  An upload is sent as the request
body itself (no multipart form), checked, and kept under the data directory.
/api/inputs/weekly/{week_ending}/analyst is the "Weekly analyst inputs" form beside them: the
figures only the analysts hold, typed when no workbook is sent (cytonn_weekly/weekly/analyst.py).

Run from backend/ (the package is installed editable):

    uvicorn api.main:app --port 8000

Every write endpoint is stateless: it loads the review fresh from review_store, mutates
it with the review.model methods, saves it, and returns the whole updated review,
the same read-modify-write the Streamlit screen did per callback.  The routes are in
api/routers/ (one module per area, each a make_router(deps)), the state they share is
api.deps.Deps, and this module only builds the app.  The API adds three guards the store
does not provide on its own:

* a decided review is read-only here.  review_store only rejects a save that disagrees
  with the stored decision, and a freshly loaded decided review agrees with it, so
  without this check its items could still be rewritten;
* writes run one at a time (one process-wide lock), because two quick clicks arrive as
  two concurrent requests and each one rewrites the whole items blob;
* only a few drafts run at once (CYTONN_DRAFT_CONCURRENCY seats, default 3), across every
  section, because a draft takes minutes and (on Bedrock) spends real budget.
  A run that finds the seats taken waits in a bounded first-in-first-out queue
  (CYTONN_DRAFT_QUEUE_MAX) and starts when a seat frees.  The seats (api/draft_slot.py) record
  which sections hold one and since when, so the overview can show them, and a claim that has
  run far longer than any healthy draft is taken over, so a hung draft cannot block drafting
  forever.  Seats, queue and run registry are in this process's memory: the API must run as
  one process (threads), never several workers.

The tool never approves anything: /decide only records the analyst's call, and
CoordinatorReview.decide() decides whether it is allowed.
"""

import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Union

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cytonn_weekly import db as database
from cytonn_weekly.common import gather as source_gather
from cytonn_weekly.common import sources as source_store
from cytonn_weekly.env import key_override_warnings, load_env
from cytonn_weekly.narrative import bedrock_provider
from cytonn_weekly.notable.registry import Detector
from cytonn_weekly.weekly import cbk_bulletin, cbk_rates

from api.deps import Deps, configured_provider
from api.draft_slot import DRAFT_STALE_AFTER_SECONDS
from api.problems import ProblemError, problem_handler
from api.routers import drafts, export, inputs, notable, overview, reviews, sources, snips
from api.runs import SSE_KEEPALIVE_SECONDS

log = logging.getLogger(__name__)

CORS_ENV_VAR = "CYTONN_WEB_ORIGINS"
DEFAULT_WEB_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


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

    app = FastAPI(title="Cytonn Weekly: analyst review")
    app.add_exception_handler(ProblemError, problem_handler)
    origins = [o.strip() for o in os.environ.get(CORS_ENV_VAR, DEFAULT_WEB_ORIGINS).split(",") if o.strip()]
    # Content-Disposition is exposed so the web app can read the exported report's file name.
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Disposition"])

    deps = Deps(db_path, draft_stale_after=draft_stale_after, clock=clock, run_keepalive=run_keepalive, inputs_root=inputs_root,
                fetch_bulletin=fetch_bulletin, export_root=export_root, fetch_usd_rates=fetch_usd_rates,
                notable_registry=notable_registry, charts_root=charts_root, sources_root=sources_root,
                fetch_source=fetch_source, search_sources=search_sources)
    # The order is the order the routes were first registered in; where two patterns can match one path the earlier wins
    # (/api/reviews/latest before /api/reviews/{run_id}; notes, analyst and charts before the {slot} upload), and each of
    # those pairs sits inside one module in that order (tests/test_api_routes.py locks them).
    for area in (overview, reviews, inputs, export, notable, sources, snips, drafts):
        app.include_router(area.make_router(deps))

    def interrupt_leftover_runs() -> None:
        """A run still queued or running in storage belongs to a process that is gone: mark it interrupted (run_store.py)."""
        found = deps.run_store.interrupt_active()
        if found:
            log.warning("%d draft run(s) were still queued or running when the tool last stopped; marked interrupted", found)

    app.router.on_startup.append(interrupt_leftover_runs)
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
