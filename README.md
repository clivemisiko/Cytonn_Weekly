# Cytonn Weekly

Tooling to automate drafting, checking and publishing the Cytonn weekly report.

See [CLAUDE.md](CLAUDE.md) for full project context and the task backlog.

## Setup

The project has two folders: `backend/` (Python: the package in `backend/src/`, the API in `backend/api/`, `backend/scripts/`, `backend/tests/`, `backend/data/`) and `frontend/` (the Next.js web app). `.env` stays in the repo root.

```sh
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e .
playwright install chromium
python -m pytest -q            # the test suite
```

## Coordinator review screen (Digital Payments)

A FastAPI layer (`backend/api/`) over `review_store`, `review_run` and `coordinator_review`, and a Next.js app (`frontend/`) that talks to it. Run both:

```sh
cd backend
uvicorn api.main:app --port 8000        # terminal 1: the API (loads the repo-root .env at startup)
cd frontend && npm install              # terminal 2, first time only
npm run dev                             # terminal 2: the web app, at http://localhost:3000 (landing page; the overview is /overview)
```

The web app calls the API at `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`; set it in `frontend/.env.local`). The API accepts browser requests from `http://localhost:3000` and `http://127.0.0.1:3000`; set `CYTONN_WEB_ORIGINS` (comma-separated) to allow another origin. The API has no authentication of its own, so keep it on localhost or behind the SSO'd network.

The screen's "Draft this week's section" button runs the real pipeline (price fetch, drafting, checks) and loads the result. That uses the drafting provider below, so the default Anthropic provider spends API budget; `CYTONN_LLM_PROVIDER=local` is the free dev option (output not for publication, and the screen says so). A draft takes minutes. It is saved on the server when it finishes even if the browser gives up waiting, and only one draft runs at a time.

The review is saved to `backend/data/app.db` (table `coordinator_reviews`, defined in `backend/src/cytonn_weekly/schema.sql`) when the draft lands, on every resolution change, and on the decision. After a refresh, the start screen offers to resume today's saved review instead of re-drafting; a decided review is frozen and can only be viewed. Code that needs the approved values reads them with `review_store.load_latest_review()`.

Endpoints, all under `/api` (see `backend/api/main.py`): `GET /config`, `GET /reviews/latest?run_date=today`, `GET /reviews/{run_id}`, `POST /reviews/draft`, `PATCH /reviews/{run_id}/items/{index}`, `POST /reviews/{run_id}/accept-clean`, `POST /reviews/{run_id}/decide`. A rejected write (not approvable, already decided) is a 409.

## Run with Docker

Docker Desktop must be running first (on Windows, start it and wait until it says the engine is running). All commands are run from the repo root.

```sh
cp .env.example .env
```

First-time setup: copies the list of settings to `.env`; fill in the ones you need (skip it if `.env` already exists).

```sh
docker compose up --build
```

Builds the two images and starts the API and the web app. Then open http://127.0.0.1:3000 (the API is at http://127.0.0.1:8000). Both are reachable from this machine only: the app has no sign-in, so the ports are published on 127.0.0.1 and must stay there.

```sh
docker compose down
```

Stops both. The database is kept, in the `cytonn_data` volume.

```sh
docker compose run --rm api pytest
```

Runs the test suite inside the API image.

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The development override: the source folders are mounted into the containers and both servers reload when a file changes.

The local development model (Ollama) stays on the host; the container reaches it at `http://host.docker.internal:11434`.

## Moving the existing database into Docker

The Docker app keeps its database in the `cytonn_data` volume, which starts empty. To start it from the reviews already saved natively, copy `backend/data/app.db` into the volume once, from the repo root:

```sh
docker compose run --rm --no-deps -v "./backend/data:/from:ro" api cp /from/app.db /app/data/app.db
```

It starts a one-off `api` container with `backend/data` mounted read-only at `/from` and copies the file into the volume as the app's own user, so the app can write to it. It overwrites any `app.db` already in the volume.

**Stop both apps first**: the native API (uvicorn) and the Docker one (`docker compose down`). A database copied while either is writing to it can be incomplete.

**After the copy the native app and the Docker app have SEPARATE databases.** A review saved in one is not in the other, and nothing syncs them. `backend/data/app.db` is left as it is.

## Drafting provider (Digital Payments)

`CYTONN_LLM_PROVIDER` picks who drafts the Weekly Highlights and outlook: `anthropic` (default, production) or `local` (development only, prints a NOT FOR PUBLICATION warning).

Local mode uses Ollama for drafting and Exa (`EXA_API_KEY`) for search:

```sh
ollama pull phi4-mini                         # default model, ~2.5 GB
CYTONN_LLM_PROVIDER=local python scripts/check_digital_payments_highlights_live.py   # from backend/
```

To A/B another model on the same search results, set `CYTONN_LOCAL_MODEL`, e.g. `gemma4:26b-a4b-it-qat` (a ~15.6 GB pull; needs well over 16 GB of free RAM or a large GPU). The first run saves each company's Exa results to `backend/data/exa_cache/<company>_<date>.json`, and later runs, whatever the model, reuse them. The cache is keyed by calendar day, so compare models on the same day. **To force a fresh Exa pull**, set `CYTONN_EXA_REFRESH=1`, or delete the file (or the whole `backend/data/exa_cache/` directory).

