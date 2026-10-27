"""The review API for the end-to-end tests: a throwaway copy of the synthetic demo week, never the real data.

    python e2e/serve_e2e.py            (Playwright starts it; see playwright.config.ts)

Every start wipes E2E_DATA_DIR and copies E2E_PRISTINE into it, so each full test run begins from the same state
(approvals and rejections are final, so a run cannot be repeated on used data). Both folders default to
backend/data/demo-e2e/, which is gitignored. It refuses to start on the real data folder.

It also never reaches the real database (fixed 2026-10-22, see CLAUDE.md): CYTONN_DATABASE_URL, CYTONN_TEST_DATABASE_URL
and CYTONN_DATABASE_SCHEMA are removed from the process first, every store call goes to the SQLite file e2e.db in the
demo data folder (create_app gets it explicitly and does not load .env), and verify_isolated() exits non-zero before
anything is served unless that is the target. tests/test_e2e_isolation.py pins it.
What differs from the real API, all of it set here and nothing in the backend changed:
- narrative pieces come from the test suite's fake provider (no model, no web search, no key);
- CYTONN_LLM_PROVIDER is "local", so no draft can spend API budget and the DEV MODE marks show;
- the weekly Real Estate draft always fails, so the suite has a stopped run to look at. While the file
  <data folder>/e2e-hold exists it waits first, so a test can keep the one draft slot held for as long as it needs;
- the weekly Digital Payments draft runs the real pipeline on the test suite's fixed price rows and fake provider,
  and every Markets Review section runs on the test suite's captured sources (tests/periodic_helpers.py), so neither
  reaches Yahoo, CBK, KNBS, afx or the NSE;
- "Fetch from CBK" is answered from the bulletin saved in backend/tests/fixtures/sources, never by CBK;
- four more Fridays hold invented equities workbooks for the chart tests (e2e/chart_demo.py): one that draws both charts,
  one with rows left out of the series, one not yet updated for the week and one with no workbook; the Equities draft for
  those weeks reads no outside source;
- the "Notable this week" panel has invented items here (e2e/notable_demo.py, each marked "invented demo item"), passed to
  create_app() as its notable_registry. The real app passes none, so its registry is empty and it shows nothing.

E2E_VARIANT starts it in another state, for the tests that need one:
- "no-key": the provider is "anthropic" with no API key, so every drafting section shows a provider problem;
- "stale":  a draft that has held the slot for six seconds counts as stuck.

The weekly Fixed Income and Equities drafts, and the suggested running totals, still read CBK's and
cytonnreport.com's public pages, as the demo instance does.
"""
import os
import shutil
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
REAL = BACKEND / "data"
DATA = Path(os.environ.get("E2E_DATA_DIR", REAL / "demo-e2e" / "data")).resolve()
PRISTINE = Path(os.environ.get("E2E_PRISTINE", REAL / "demo-e2e" / "pristine")).resolve()
PORT = int(os.environ.get("E2E_API_PORT", "8011"))
VARIANT = os.environ.get("E2E_VARIANT", "")
FAILURE = "E2E: the Ibuka summary could not be fetched (a deliberate failure for the tests)."
HOLD = DATA / "e2e-hold"
FIXTURES = BACKEND / "tests" / "fixtures" / "sources"

DATABASE_ENV = ("CYTONN_DATABASE_URL", "CYTONN_TEST_DATABASE_URL", "CYTONN_DATABASE_SCHEMA")


def clear_database_env() -> None:
    """The e2e instance is never on PostgreSQL: the variables that would send it there are removed from this process."""
    for name in DATABASE_ENV:
        os.environ.pop(name, None)


def verify_isolated(db_path: Path, data: Path) -> None:
    """Fail closed: exit non-zero (the message names no URL) unless the database target is the SQLite file in `data`.

    Nothing is opened: db.target() says where connect() would go.  No database variable may be set, the explicit path
    must be a file inside the demo data folder, and a call that is given no path (the default) must be SQLite inside
    that folder too, never PostgreSQL and never the real backend/data/app.db.
    """
    from cytonn_weekly import db  # imported here, after the variables are cleared

    clear_database_env()  # a .env loaded since (create_app does it unless told not to) would have put them back
    if any(os.environ.get(name) for name in DATABASE_ENV):
        raise SystemExit("E2E: refusing to start: a database variable is still set.")
    db_path, folder = Path(db_path).resolve(), data.resolve()
    if folder not in db_path.parents:
        raise SystemExit("E2E: refusing to start: the database file is not inside the demo data folder.")
    if db.target(db_path) != ("sqlite", db_path):
        raise SystemExit("E2E: refusing to start: the database target is not the demo SQLite file.")
    kind, default = db.target(None)
    if kind != "sqlite" or folder not in Path(default).resolve().parents:
        raise SystemExit("E2E: refusing to start: a call with no database path would not use the demo data folder.")


def prepare(data: Path = DATA, pristine: Path = PRISTINE) -> Path:
    """Clear the database variables, restore the demo data folder from the pristine copy and return the SQLite file."""
    clear_database_env()
    if not pristine.is_dir():
        raise SystemExit(f"no pristine copy at {pristine}: copy backend/data/demo/data there without its app.db (see e2e/README.md)")
    shutil.rmtree(data, ignore_errors=True)
    shutil.copytree(pristine, data)
    return data / "e2e.db"


def main() -> None:
    if DATA == REAL or REAL not in DATA.parents or DATA.parent.name != "demo-e2e":
        raise SystemExit(f"refusing to run the tests on {DATA}: the data folder must be backend/data/demo-e2e/<name>")
    if VARIANT not in ("", "no-key", "stale"):
        raise SystemExit(f"unknown E2E_VARIANT {VARIANT!r}")
    DB_PATH = prepare(DATA, PRISTINE)  # explicit, so a test can point main() at a scratch folder

    os.environ["CYTONN_DATA_DIR"] = str(DATA)
    os.environ["CYTONN_WEB_ORIGINS"] = os.environ.get("E2E_WEB_ORIGINS", "http://127.0.0.1:5183")
    os.environ["CYTONN_LLM_PROVIDER"] = "anthropic" if VARIANT == "no-key" else "local"
    os.environ["ANTHROPIC_API_KEY"] = ""  # set and empty: the environment beats .env, so no real key is ever read
    os.environ["EXA_API_KEY"] = "e2e"  # the fake provider never searches
    sys.path.insert(0, str(BACKEND))

    import uvicorn  # noqa: E402
    from api.main import create_app  # noqa: E402
    from cytonn_weekly import paths  # noqa: E402
    from cytonn_weekly.digital_payments import review_run as digital_payments  # noqa: E402
    from cytonn_weekly.narrative import drafter  # noqa: E402
    import chart_demo  # noqa: E402 - e2e/chart_demo.py, beside this file
    import notable_demo  # noqa: E402 - e2e/notable_demo.py, beside this file
    from cytonn_weekly.real_estate import review_run as real_estate  # noqa: E402
    from tests import periodic_helpers, review_helpers  # noqa: E402
    from tests.section_helpers import FakeNarrativeProvider  # noqa: E402

    assert paths.DATA_DIR == DATA, paths.DATA_DIR

    class _E2EProvider(FakeNarrativeProvider):
        # A topic that says so is drafted with a figure its cited text lacks, so the sentence-edit tests have a flagged sentence.
        def draft_piece(self, brief, **kw):
            self.bad_figure = "bad figure" in brief.label
            return super().draft_piece(brief, **kw)

    drafter.get_narrative_provider = lambda: _E2EProvider()

    def _fail(**_):
        waited = 0.0
        while HOLD.exists() and waited < 180:  # a test is holding the draft slot open
            time.sleep(0.25)
            waited += 0.25
        raise RuntimeError(FAILURE)

    real_estate.build_real_estate_review = _fail

    chart_demo.seed()
    chart_demo.offline_equities()

    _real_dp = digital_payments.build_digital_payments_review
    digital_payments.build_digital_payments_review = lambda today=None, on_event=None, **_: _real_dp(
        provider=review_helpers.FakeProvider(), today=today, fetch_table=lambda _today: review_helpers.ROWS, on_event=on_event)

    # Markets Review sections: the test suite's own builders, which hold the real ones and feed them captured sources.
    for _slug, _helper in periodic_helpers.BUILDERS.items():
        _module = __import__(f"cytonn_weekly.periodic.{_slug}", fromlist=["_"])
        setattr(_module, f"build_{_slug}_review", lambda pctx, on_event=None, _helper=_helper: _helper(pctx, on_event=on_event))

    def fetch_bulletin(issue_date: date) -> tuple[bytes, str]:
        """CBK's Weekly Bulletin for that Friday, from the saved fixture; a LookupError (the route's 404) if none is saved."""
        saved = FIXTURES / f"cbk_weekly_bulletin_{issue_date.isoformat()}.pdf"
        if not saved.is_file():
            raise LookupError(f"E2E: no bulletin is saved for {issue_date.isoformat()}")
        return saved.read_bytes(), f"https://e2e.invalid/uploads/weekly_bulletin/{saved.name}"

    print(f"E2E instance: data folder {paths.DATA_DIR}, port {PORT}, variant {VARIANT or 'default'}", flush=True)
    app = create_app(DB_PATH, load_dotenv=False, fetch_bulletin=fetch_bulletin, notable_registry=notable_demo.REGISTRY,
                     **({"draft_stale_after": 6} if VARIANT == "stale" else {}))
    verify_isolated(DB_PATH, DATA)  # fail closed, before anything is served
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
