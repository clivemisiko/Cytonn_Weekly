# Cytonn Weekly web app, Vue

A Vue 3 port of the Next.js app in `frontend/`, built beside it: the same routes, copy, design tokens and API calls.
**`frontend/` remains the live frontend** until Clive decides to cut over. `PARITY.md` is the checklist the port was
built against and says what is verified and what is not.

Vue 3 (`<script setup lang="ts">`), Vite, Vue Router, TypeScript, Tailwind v4, Reka UI, Phosphor icons. A single-page
app: no server rendering.

```sh
npm ci
npm run dev          # http://127.0.0.1:5173, /api proxied to the review API on http://127.0.0.1:8000
npm run typecheck    # vue-tsc
npm run lint         # ESLint with the Vue plugin
npm test             # Vitest: the pure helpers in src/lib
npm run check:copy   # every phrase of frontend/'s components is in this app's source
npm run build        # typecheck, then dist/
```

- **The API address.** In development and under `npm run preview` the browser only talks to this app's own origin and
  Vite proxies `/api` to the backend, so the backend needs no CORS entry for it. `VITE_API_TARGET` points the proxy at
  another instance (`VITE_API_TARGET=http://127.0.0.1:8011 npm run dev`). A built `dist/` served by anything else needs
  `/api` proxied the same way, or `VITE_API_URL` set at build time to the API's address (which then needs CORS).
- **Styles.** `src/styles.css` is `frontend/src/app/globals.css` with three marked changes (imports, font variables,
  a last block of CSS animations). Change a token in both files until the cut-over.
- **Copied files.** `src/lib/types.ts`, `format.ts`, `run.ts`, `topic.ts` and `sso.ts` are copies of the Next app's.
- **End-to-end tests** live in `../e2e/` and run against both apps.
- The server binds to 127.0.0.1 only: the app has no sign-in.
