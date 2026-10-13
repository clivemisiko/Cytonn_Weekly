"""The review API for the end-to-end tests: a throwaway copy of the synthetic demo week, never the real data.

    python e2e/serve_e2e.py            (Playwright starts it; see playwright.config.ts)

Every start wipes E2E_DATA_DIR and copies E2E_PRISTINE into it, so each full test run begins from the same state
(approvals are final, so a run cannot be repeated on used data). Both folders default to backend/data/demo-e2e/,
which is gitignored. It refuses to start on the real data folder.

What differs from the real API, all of it set here and nothing in the backend changed:
- narrative pieces come from the test suite's fake provider (no model, no web search, no key);
- CYTONN_LLM_PROVIDER is "local", so no draft can spend API budget and the DEV MODE marks show;
- the weekly Real Estate draft always fails, so the suite has a stopped run to look at.
"""
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
REAL = BACKEND / "data"
DATA = Path(os.environ.get("E2E_DATA_DIR", REAL / "demo-e2e" / "data")).resolve()
PRISTINE = Path(os.environ.get("E2E_PRISTINE", REAL / "demo-e2e" / "pristine")).resolve()
PORT = int(os.environ.get("E2E_API_PORT", "8011"))
FAILURE = "E2E: the Ibuka summary could not be fetched (a deliberate failure for the tests)."

if DATA == REAL or REAL not in DATA.parents or DATA.parent.name != "demo-e2e":
    raise SystemExit(f"refusing to run the tests on {DATA}: the data folder must be backend/data/demo-e2e/<name>")
if not PRISTINE.is_dir():
    raise SystemExit(f"no pristine copy at {PRISTINE}: copy backend/data/demo/data there without its app.db (see e2e/README.md)")
shutil.rmtree(DATA, ignore_errors=True)
shutil.copytree(PRISTINE, DATA)

os.environ["CYTONN_DATA_DIR"] = str(DATA)
os.environ["CYTONN_WEB_ORIGINS"] = os.environ.get("E2E_WEB_ORIGINS", "http://127.0.0.1:3011,http://127.0.0.1:5183")
os.environ["CYTONN_LLM_PROVIDER"] = "local"
os.environ["EXA_API_KEY"] = "e2e"  # the fake provider never searches
sys.path.insert(0, str(BACKEND))

import uvicorn  # noqa: E402
from api.main import create_app  # noqa: E402
from cytonn_weekly import paths  # noqa: E402
from cytonn_weekly.narrative import drafter  # noqa: E402
from cytonn_weekly.real_estate import review_run as real_estate  # noqa: E402
from tests.section_helpers import FakeNarrativeProvider  # noqa: E402

assert paths.DATA_DIR == DATA, paths.DATA_DIR
drafter.get_narrative_provider = lambda: FakeNarrativeProvider()


def _fail(**_):
    raise RuntimeError(FAILURE)


real_estate.build_real_estate_review = _fail

print(f"E2E instance: data folder {paths.DATA_DIR}, port {PORT}", flush=True)
uvicorn.run(create_app(), host="127.0.0.1", port=PORT, log_level="warning")
