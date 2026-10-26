# Cytonn Weekly

Tooling to automate drafting, checking and publishing the Cytonn weekly report.

See [CLAUDE.md](CLAUDE.md) for full project context and the task backlog.

## Setup

The project has two folders: `backend/` (Python: the package in `backend/src/`, the API in `backend/api/`, `backend/scripts/`, `backend/tests/`, `backend/data/`) and `frontend/` (the Vue 3 web app, built with Vite). `.env` stays in the repo root.

```sh
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e .
playwright install chromium
python -m pytest -q            # the test suite
```

## Coordinator review screen (Digital Payments)

A FastAPI layer (`backend/api/`) over `review_store`, `review_run` and `coordinator_review`, and a Vue app (`frontend/`) that talks to it. Run both:

```sh
cd backend
uvicorn api.main:app --port 8000        # terminal 1: the API (loads the repo-root .env at startup)
cd frontend && npm ci                   # terminal 2, first time only
npm run dev                             # terminal 2: the web app, at http://127.0.0.1:5173 (landing page; the overview is /overview)
```

The browser only talks to the web app's own address: its server proxies `/api` to the API at `VITE_API_TARGET` (default `http://127.0.0.1:8000`; set it in the shell before `npm run dev` to use another instance). For a page served from elsewhere, the API accepts browser requests from `http://localhost:5173` and `http://127.0.0.1:5173`; set `CYTONN_WEB_ORIGINS` (comma-separated) to allow another origin. The API has no authentication of its own, so keep it on localhost or behind the SSO'd network.

The screen's "Draft this week's section" button runs the real pipeline (price fetch, drafting, checks) and loads the result. That uses the drafting provider below, so the default Anthropic provider spends API budget; `CYTONN_LLM_PROVIDER=local` is the free dev option (output not for publication, and the screen says so). A draft takes minutes. It is saved on the server when it finishes even if the browser gives up waiting, and only one draft runs at a time.

The review is saved to `backend/data/app.db` (table `coordinator_reviews`, defined in `backend/src/cytonn_weekly/schema.sql`) when the draft lands, on every resolution change, and on the decision. After a refresh, the start screen offers to resume today's saved review instead of re-drafting; a decided review is frozen and can only be viewed. Code that needs the approved values reads them with `review_store.load_latest_review()`.

Endpoints, all under `/api` (see `backend/api/main.py`): `GET /config`, `GET /reviews/latest?run_date=today`, `GET /reviews/{run_id}`, `POST /reviews/draft`, `PATCH /reviews/{run_id}/items/{index}`, `POST /reviews/{run_id}/accept-clean`, `POST /reviews/{run_id}/decide`. A rejected write (not approvable, already decided) is a 409.

## Run with Docker

Docker Desktop must be running first (on Windows, start it and wait until it says the engine is running). Run from the repo root, in PowerShell. `.env` must hold `CYTONN_DATABASE_URL`: the Docker app uses the same Supabase database as the native one and refuses to start without it (it never falls back to SQLite).

```powershell
docker compose up -d --build        # build the two images and start them in the background
docker compose ps                   # both should say "healthy" (web waits for api)
docker compose logs --tail 50 api   # the API's last 50 lines
docker compose down                 # stop both
```

Then open http://127.0.0.1:5173 (the API is at http://127.0.0.1:8000), the same addresses as a native run. **Run one copy at a time**: stop the native API and `npm run dev` before starting Docker, and `docker compose down` before running natively, or the ports clash. Both are reachable from this machine only: the app has no sign-in, so the ports are published on 127.0.0.1 and must stay there.

- **Files:** `backend/data` is bind-mounted into the API container, so inputs, charts, exports and the search cache are the same files as a native run. There is no Docker volume and nothing to copy.
- **Secrets:** they reach the container from `.env` at run time only (`env_file`), never an image. Never run `docker compose config` without `--quiet` or `--no-env-resolution`: it prints what `.env` holds.
- **Web:** the built app is served by nginx (`frontend/nginx.conf`), which proxies `/api` to the API, the run view's live stream included.
- **Tests** are not in the runtime image. `docker build --target test -t cytonn-api-test backend` then `docker run --rm --network none cytonn-api-test` runs the suite without `.env` or the data folder.
- **Development override** (`docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`): source mounted, both servers reload. Updated for nginx but not yet run.
- The local development model (Ollama) stays on the host; the container reaches it at `http://host.docker.internal:11434`.

## Drafting provider (Digital Payments)

`CYTONN_LLM_PROVIDER` picks who drafts the Weekly Highlights and outlook: `anthropic` (default, production) or `local` (development only, prints a NOT FOR PUBLICATION warning).

Local mode uses Ollama for drafting and Exa (`EXA_API_KEY`) for search:

```sh
ollama pull phi4-mini                         # default model, ~2.5 GB
CYTONN_LLM_PROVIDER=local python scripts/check_digital_payments_highlights_live.py   # from backend/
```

To A/B another model on the same search results, set `CYTONN_LOCAL_MODEL`, e.g. `gemma4:26b-a4b-it-qat` (a ~15.6 GB pull; needs well over 16 GB of free RAM or a large GPU). The first run saves each company's Exa results to `backend/data/exa_cache/<company>_<date>.json`, and later runs, whatever the model, reuse them. The cache is keyed by calendar day, so compare models on the same day. **To force a fresh Exa pull**, set `CYTONN_EXA_REFRESH=1`, or delete the file (or the whole `backend/data/exa_cache/` directory).

