# End-to-end tests

One Playwright suite (Chromium, T01 to T69) for the web app in `frontend/`. `frontend/PARITY.md` says which test
covers which behaviour.

## The backend the tests use

Never the real one. `serve_e2e.py` starts the review API on **127.0.0.1:8011** over a throwaway copy of the synthetic
demo week, and restores that copy from a pristine one at every start, because the suite approves a section and an
approval is final. It refuses to start on `backend/data` itself. Narrative pieces come from the test suite's fake
provider (no model, no web search, no key), the provider is set to `local` so nothing can spend API budget, and the
weekly Real Estate draft is made to fail so there is a stopped run to look at. Nothing in `backend/` is changed.

The weekly Fixed Income and Equities drafts, and the suggested running total in T20, still read CBK's and
cytonnreport.com's public pages, as the demo instance does, so T12, T13 and T20 need the network.

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
already has a review) and `tests/notable.spec.ts` (T47 to T58: the "Notable this week" panel on invented demo items, and the working chart at 390px and on a desktop) and `tests/rail.spec.ts` (T59 to T65 and T69: the side rail and the shell's dev ribbon) and `tests/overview.spec.ts` (T66 to T68: the report-status panel and the section cards), each with its own start of the API and so on freshly restored data: a section that has a review
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
