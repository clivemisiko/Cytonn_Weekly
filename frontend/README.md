# Cytonn Weekly web app

The coordinator's web app: the landing page, the overview with its start and review screens, and the draft run view.
It replaced the Next.js app that lived in this folder until 2026-10-13 (kept at the local git tag
`last-next-frontend`). `PARITY.md` is the checklist it was built against, kept as a record.

Vue 3 (`<script setup lang="ts">`), Vite, Vue Router, TypeScript, Tailwind v4, Reka UI, Phosphor icons. A single-page
app: no server rendering.

```sh
npm ci
npm run dev          # http://127.0.0.1:5173, /api proxied to the review API on http://127.0.0.1:8000
npm run typecheck    # vue-tsc
npm run lint         # ESLint with the Vue plugin
npm test             # Vitest: the pure helpers in src/lib
npm run build        # typecheck, then dist/
```

- **The API address.** In development and under `npm run preview` the browser only talks to this app's own origin and
  Vite proxies `/api` to the backend, so the backend needs no CORS entry for it. `VITE_API_TARGET` points the proxy at
  another instance (`VITE_API_TARGET=http://127.0.0.1:8011 npm run dev`). A built `dist/` served by anything else needs
  `/api` proxied the same way, or `VITE_API_URL` set at build time to the API's address (which then needs CORS).
- **Styles.** `src/styles.css` holds every design token; no component holds a colour of its own.
- **Docker.** `Dockerfile` builds `dist/` and serves it with `vite preview` on port 3000, with `/api` proxied to the
  `api` service (see `../docker-compose.yml`).
- **End-to-end tests** live in `../e2e/`.
- The server binds to 127.0.0.1 only: the app has no sign-in.
