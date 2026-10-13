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

The Fixed Income and Equities drafts still read CBK's and cytonnreport.com's public pages, as the demo instance does,
so those two tests need the network.

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
