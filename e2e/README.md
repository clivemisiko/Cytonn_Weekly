# End-to-end tests

One Playwright suite (`tests/app.spec.ts`, Chromium) that runs unchanged against both frontends: the Next.js app in
`frontend/` and the Vue app in `frontend-vue/`. A pass on both means the same behaviour. `frontend-vue/PARITY.md`
says which test covers which behaviour.

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

Playwright starts the API and the app under test itself, and stops them afterwards. From `e2e/`:

```sh
npm run test:vue                                     # frontend-vue on Vite's dev server (127.0.0.1:5183)
E2E_NEXT_DIR=<a build of frontend/> npm run test:next   # the Next app (127.0.0.1:3011)
```

The Next app fixes the API's address into the browser code when it is built, so the tests need a build made with
`NEXT_PUBLIC_API_URL=http://127.0.0.1:8011`. `next dev` refuses a second server from `frontend/` while one is running
there and a build in place would write into the same folder, so build a copy outside the repository and point
`E2E_NEXT_DIR` at it:

```sh
git archive HEAD frontend | tar -x -C <scratch>
cd <scratch>/frontend && npm ci && NEXT_PUBLIC_API_URL=http://127.0.0.1:8011 npx next build
```

`npm run test:vue` and `npm run test:next` run `tests/app.spec.ts` (T01 to T16) and then `tests/more.spec.ts` (T17 to
T25), each with its own start of the API and so on freshly restored data: a section that has a review no longer
offers its start screen, and the first file leaves several in review. Run one file with `npx playwright test app` or
`npx playwright test more` (not both in one command). Two tests
need the API started in another state, so they have their own runs, one start of the API each:

```sh
npm run test:variants          # T26 with E2E_VARIANT=no-key, then T27 with E2E_VARIANT=stale; E2E_TARGET picks the app (vue by default)
```

In Windows PowerShell, set a variable with `$env:NAME = "value"` first, for example
`$env:E2E_NEXT_DIR = "C:\path\to\copy\frontend"; npm run test:next` and `$env:E2E_TARGET = "next"; npm run test:variants`.

What the test API does so that these tests need no outside service (all in `serve_e2e.py`, nothing in `backend/`):

- while the file `backend/data/demo-e2e/data/e2e-hold` exists, the weekly Real Estate draft waits before it fails, so a
  test can keep the one draft slot held (T24, T27);
- the weekly Digital Payments draft runs the real pipeline on the unit tests' fixed price rows and fake provider (T22),
  and every Markets Review section runs on the unit tests' captured sources (T25);
- "Fetch from CBK" is answered from the bulletin saved in `backend/tests/fixtures/sources` (T17);
- `no-key` sets the provider to `anthropic` with an empty key (a provider problem, T26); `stale` counts a draft as
  stuck after six seconds (T27).

`E2E_BASE_URL` with `E2E_NO_WEB=1` runs the suite against an app you started yourself; the API must then allow that
origin (`E2E_WEB_ORIGINS`).

## Screenshots

`npm run shots` (with `E2E_TARGET` as above) writes every page and state in light and dark, at desktop width and at
390 px, to `screenshots/parity/<target>/` at the repository root (ignored by git). It drafts and approves on the test
backend like the suite does.

## What is stood in for

The Word export needs all six sections approved, and three of them need live sources the test instance does not have.
T14 checks the real disabled state, then answers the two export calls itself to check what the page does when the API
says the report is ready (the button enables, the file downloads under the name the API gives).
