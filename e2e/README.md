# End-to-end tests

One Playwright suite (Chromium, T01 to T86) for the web app in `frontend/`. `frontend/PARITY.md` says which test
covers which behaviour.

## The backend the tests use

Never the real one. `serve_e2e.py` starts the review API on **127.0.0.1:8011** over a throwaway copy of the synthetic
demo week, and restores that copy from a pristine one at every start, because the suite approves a section and an
approval is final. It refuses to start on `backend/data` itself. Narrative pieces come from the test suite's fake
provider (no model, no web search, no key), the provider is set to `local` so nothing can spend API budget, and the
weekly Real Estate draft is made to fail so there is a stopped run to look at. Nothing in `backend/` is changed.

The weekly Fixed Income and Equities drafts, and the suggested running total in T20, still read CBK's and
cytonnreport.com's public pages, as the demo instance does, so T12, T13 and T20 need the network.

**The database.** The instance runs on its own SQLite file, `e2e.db` in the demo data folder, and can never reach
PostgreSQL: `serve_e2e.py` removes `CYTONN_DATABASE_URL`, `CYTONN_TEST_DATABASE_URL` and `CYTONN_DATABASE_SCHEMA` from its
process, gives `create_app` the SQLite path (and no `.env`), and exits non-zero before it serves anything unless that is the
target (`backend/tests/test_e2e_isolation.py`). Between the PostgreSQL go-live on 2026-10-22 and this fix it was not so: a `.env`
with `CYTONN_DATABASE_URL` sent the demo and the suite to the real database. As a second lock, run the suite with a dead
address in the process environment, which beats `.env`:

```sh
CYTONN_DATABASE_URL="postgresql://x:y@127.0.0.1:1/z?sslmode=require" npm exec --no-install -- playwright test app
```

Set up once (both folders are under `backend/data/`, which git ignores):

```sh
mkdir -p backend/data/demo-e2e
cp -r backend/data/demo/data backend/data/demo-e2e/pristine
rm -f backend/data/demo-e2e/pristine/app.db          # start with no reviews; the uploaded inputs stay
cd e2e && npm ci && npx playwright install chromium
```

## Running

Playwright starts the API and the app itself, and stops them afterwards. From `e2e/`:

```sh
npm test                       # frontend/ on Vite's dev server (127.0.0.1:5183), /api proxied to the test API
```

`npm test` runs `tests/app.spec.ts` (T01 to T16), then `tests/more.spec.ts` (T17 to T25) and then
`tests/buttons.spec.ts` (T28 to T36: every button of the two input panels with the week before present and absent) and
`tests/notes.spec.ts` (T37 to T39: the notes of a rejected draft shown on the next one) and `tests/links.spec.ts`
(T40 and T41: web links in Company Updates) and `tests/draftagain.spec.ts` (T42 to T46: "Draft again" on a section that
already has a review) and `tests/notable.spec.ts` (T47 to T58: the "Notable this week" panel on invented demo items, and the working chart at 390px and on a desktop) and `tests/rail.spec.ts` (T59 to T65 and T69: the side rail and the shell's dev ribbon) and `tests/overview.spec.ts` (T66 to T68 and T70: the report-status panel, the section cards and the export's dev-mode notice) and `tests/startscreen.spec.ts` (T71: the start screen's panel) and `tests/reviewscreen.spec.ts` (T72: the review screen's layout) and `tests/runview.spec.ts` (T73 to T75: the run view's facts panel, a stopped run's failure and way back, a run the API no longer has) and `tests/startpages.spec.ts` (T76 and T77: the start page as one centred card, the not-found card) and `tests/chartcard.spec.ts` (T78 to T86: the chart card on the Equities review, on four demo Fridays that hold invented equities workbooks; T85 writes screenshots only when `E2E_SHOTS` names a folder, for example `E2E_SHOTS=../screenshots/charts npx playwright test chartcard`, and is skipped otherwise), each with its own start of the API and so on freshly restored data: a section that has a review
offers its start screen only through its card's "Draft again" button, and the first file leaves several in review. Run one file with `npx playwright test app` or
`npx playwright test more` (not both in one command). Two tests
need the API started in another state, so they have their own runs, one start of the API each:

```sh
npm run test:variants          # T26 with E2E_VARIANT=no-key, then T27 with E2E_VARIANT=stale
```

What the test API does so that these tests need no outside service (all in `serve_e2e.py`, nothing in `backend/`):

- while the file `backend/data/demo-e2e/data/e2e-hold` exists, the weekly Real Estate draft waits before it fails, so a
  test can keep the one draft slot held (T24, T27);
- the weekly Digital Payments draft runs the real pipeline on the unit tests' fixed price rows and fake provider (T22),
  and every Markets Review section runs on the unit tests' captured sources (T25);
- "Fetch from CBK" is answered from the bulletin saved in `backend/tests/fixtures/sources` (T17);
- four more Fridays (2026-09-25, 09-18, 09-11 and 09-04) hold invented equities workbooks for the chart tests (`e2e/chart_demo.py`): one that draws
  both charts, one with rows left out of the series, one not yet updated for the week and one with no workbook; the Equities draft for those
  weeks reads no outside source (T78 to T86);
- the "Notable this week" panel has invented items here (`e2e/notable_demo.py`: invented series run through the real detector
  library, each item marked "invented demo item"), passed to
  `create_app()` as `notable_registry`; the real app passes none, so it shows nothing (T47 to T58). Each of those tests uses its own Friday,
  because a decision belongs to its week;
- `no-key` sets the provider to `anthropic` with an empty key (a provider problem, T26); `stale` counts a draft as
  stuck after six seconds (T27).

`E2E_BASE_URL` with `E2E_NO_WEB=1` runs the suite against an app you started yourself; the API must then allow that
origin (`E2E_WEB_ORIGINS`).

## What is stood in for

The Word export needs all six sections approved, and three of them need live sources the test instance does not have.
T14 checks the real disabled state, then answers the two export calls itself to check what the page does when the API
says the report is ready (the button enables, the file downloads under the name the API gives).
