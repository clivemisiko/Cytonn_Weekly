# Parity checklist: frontend/ (Next.js) to frontend-vue/ (Vue 3)

The checklist for the Vue port. `frontend/` is the live frontend and is not changed by this work. One row per thing the
Next app does. **Vue** is the state of the port: `todo`, `done` (ported, checked by hand or by typecheck only), or
`verified by Tn` (test `Tn` of `e2e/tests/app.spec.ts` passes against both apps). **Test** names the test that covers
the behaviour on the Next app; `none` means no automated test, with the reason in the notes at the foot.

Source paths are under `frontend/src/`; Vue paths under `frontend-vue/src/`.

## 1. Routes and pages

| # | Route | What it shows | Next source | Vue | Test |
| --- | --- | --- | --- | --- | --- |
| R1 | `/` | Landing page: greeting by the viewer's clock, "Ready" line, disabled SSO button, "Continue without signing in", no-sign-in notice. Makes no API call. | `app/page.tsx`, `components/landing/landing-page.tsx` | todo | T01 |
| R2 | `/?report=`, `?period=`, `?kind=` | Old bookmark: redirects to `/overview` with the whole query string kept | `app/page.tsx` | todo | T02 |
| R3 | `/overview` | Phase machine: booting, unreachable, overview, start, review. Report mirrored in the address bar (`?report=&period=&kind=`), absent means weekly; a report the API rejects (422) falls back to weekly | `app/overview/page.tsx`, `components/review/review-app.tsx` | todo | T03, T04 |
| R4 | `/overview?review=<id>` | Opens that saved review directly; if it cannot be read, the overview | `review-app.tsx` (`reviewFromUrl`, `boot`) | todo | T09 |
| R5 | `/runs/:runId` | The draft run view | `app/runs/[runId]/page.tsx`, `components/run/run-view.tsx` | todo | T09, T11, T12, T15 |
| R6 | every page | Root layout: `<html lang="en">`, title "Cytonn Weekly review", description, theme-color metas (#0a2b29 light, #0e2421 dark), the two fonts, skip link, top bar | `app/layout.tsx` | todo | T16 |

## 2. Components

| # | Component | Next source | Vue file | Vue |
| --- | --- | --- | --- | --- |
| C1 | TopBar (Home, Back, theme) | `components/nav/top-bar.tsx` | `components/nav/TopBar.vue` | todo |
| C2 | ThemeToggle (radio group of three) | `components/nav/theme-toggle.tsx` | `components/nav/ThemeToggle.vue` | todo |
| C3 | LandingPage | `components/landing/landing-page.tsx` | `pages/LandingPage.vue` | todo |
| C4 | ReviewApp (phase machine, Booting, Unreachable) | `components/review/review-app.tsx` | `pages/OverviewPage.vue` | todo |
| C5 | Masthead | `components/review/masthead.tsx` | `components/review/Masthead.vue` | todo |
| C6 | Notice, DevRibbon, DevAlert, LockBar | `components/review/banners.tsx` | `components/review/Notice.vue`, `DevRibbon.vue`, `LockBar.vue` | todo |
| C7 | OverviewScreen (StateChip, Progress, SectionRow, Tally) | `components/review/overview-screen.tsx` | `components/review/OverviewScreen.vue`, `SectionRow.vue` | todo |
| C8 | ReportPicker | `components/review/report-picker.tsx` | `components/review/ReportPicker.vue` | todo |
| C9 | Drafting poll, live elapsed, DraftingBanner, DraftingChip | `components/review/drafting.tsx` | `lib/drafting.ts`, `components/review/DraftingBanner.vue`, `DraftingChip.vue` | todo |
| C10 | ExportBar | `components/review/export-bar.tsx` | `components/review/ExportBar.vue` | todo |
| C11 | StartScreen (ServerDraftingNotice, FromTheReport) | `components/review/start-screen.tsx` | `components/review/StartScreen.vue` | todo |
| C12 | InputsPanel (StateChip, FileLine, Slot) | `components/review/inputs-panel.tsx` | `components/review/InputsPanel.vue`, `InputSlot.vue`, `ToneChip.vue` | todo |
| C13 | AnalystPanel (OriginChip, Provenance, Differences, Confirm, FieldRow, RowsPreview, TableHead, TableNotes, PasteTable, GridTable) | `components/review/analyst-panel.tsx` | `components/review/analyst/*.vue`, `lib/analyst.ts` | todo |
| C14 | ReviewScreen | `components/review/review-screen.tsx` | `components/review/ReviewScreen.vue` | todo |
| C15 | StatusBar (Message) | `components/review/status-bar.tsx` | `components/review/StatusBar.vue` | todo |
| C16 | DecisionControls (confirm dialog) | `components/review/decision-controls.tsx`, `components/ui/dialog.tsx` | `components/review/DecisionControls.vue` (Reka Dialog) | todo |
| C17 | Scorecard, CountTile | `components/review/scorecard.tsx`, `run-view.tsx` | `components/review/Scorecard.vue`, `CountTile.vue` | todo |
| C18 | DraftPane (Numeral, Warnings, Highlight, DataTable, StockTable, OutlookBlock) | `components/review/draft-pane.tsx` | `components/review/DraftPane.vue`, `DataTable.vue`, `Numeral.vue`, `Warnings.vue` | todo |
| C19 | BlocksPane (Narrative, Table, Computed, Carried, Unavailable, Supplied, ChartNotes, NotCoveredNotes, summary) | `components/review/blocks-pane.tsx` | `components/review/BlocksPane.vue` | todo |
| C20 | ItemsPane (collapsible groups, accept-clean) | `components/review/items-pane.tsx`, `components/ui/collapsible.tsx` | `components/review/ItemsPane.vue` (Reka Collapsible) | todo |
| C21 | ReviewItemCard (FlagDetail, Detail, note box) | `components/review/review-item-card.tsx` | `components/review/ReviewItemCard.vue` | todo |
| C22 | ResolutionControl (segmented radio group) | `components/review/resolution-control.tsx` | `components/review/ResolutionControl.vue` (Reka RadioGroup) | todo |
| C23 | Markdown (no raw HTML, safe links, new tab) | `components/review/markdown.tsx` | `components/review/Markdown.vue` (markdown-it, `html: false`) | todo |
| C24 | RunView (Mark, Step, CountTile, Shell) | `components/run/run-view.tsx` | `pages/RunPage.vue` | todo |
| C25 | Button (variants and sizes), Skeleton, Textarea | `components/ui/button.tsx`, `skeleton.tsx`, `textarea.tsx` | `components/ui/Button.vue`, `button.ts`, `Textarea.vue` | todo |

## 3. Backend calls

All through `lib/api.ts` (`request()`): JSON, `cache: "no-store"`, a 30 s timeout (180 s for uploads, form saves, carry,
suggest, bulletin fetch). Errors become `ApiError(message, status)`: the API's `detail` string, or FastAPI's validation
list joined with "; ", or "<status> <statusText>"; `status` is null when no answer arrived ("Could not reach the review
API at <base>. Is it running?" or "The request timed out after N seconds."). In the Vue app the base is the page's own
origin and Vite proxies `/api` to the backend, so the "could not reach" message names the page's origin.

| # | Call | Payload | Where | Loading shown as | Error shown as | Vue | Test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `GET /api/config` | none | overview boot, start screen, run view | Booting skeleton (overview) | Unreachable screen with the message and "Try again"; ignored on the run view | todo | T03 |
| A2 | `GET /api/sections?report_type=&period=&kind=` | query | overview, start screen, the 5 s drafting poll, after a 409 on draft | Booting skeleton; picker button "Loading…" | 422 under the picker's period (role=alert); on boot a 422 falls back to weekly; other errors: Unreachable; a failed poll is retried silently | todo | T03, T04 |
| A3 | `POST /api/runs` | `{section, report_type, period or null, kind, topic?, text?, provider?}` | start screen draft button | Button "Starting…", inputs disabled | Notice role=alert with the API's message; "Check for a saved draft" when status is null or 409 | todo | T09, T11, T12 |
| A4 | `GET /api/runs/{id}` | none | run view: first read, 2 s poll, once after the last event | "Loading the run…" | 404: "This run is no longer available…"; other failure: "Not connected." and the Connection lost notice | todo | T09, T15 |
| A5 | `GET /api/runs/{id}/events` (EventSource, event `step`) | none | run view | status line "Running. Started …" | on error the source is closed for good: `poll` ("Live updates are off; checking every 2 seconds.") if it never opened, `lost` ("Connection lost. …") if it dropped | todo | T12 |
| A6 | `GET /api/reviews/{id}` | none | resume, `?review=`, re-sync after a failed write | Booting skeleton | Unreachable screen (resume); overview (deep link) | todo | T09 |
| A7 | `PATCH /api/reviews/{id}/items/{index}` | `{resolution}` or `{resolution, note}` | resolution control, note box on blur or Enter | status bar "Saving…"; the control shows the pending choice at once | status bar "Not saved" and "NOT SAVED: … The last change did not reach the server; the screen shows what the server holds."; review re-read | todo | T09, T12 |
| A8 | `POST /api/reviews/{id}/accept-clean` | none | "Mark all clean as accepted (N unresolved)" | "Saving…" | as A7 | todo | T12 |
| A9 | `POST /api/reviews/{id}/decide` | `{decision}` | confirm dialog | dialog button "Recording…", buttons disabled | Notice role=alert in the status bar; review re-read | todo | T09 |
| A10 | `GET /api/inputs/weekly/{week}` | none | inputs panel | "Reading what has been received for the week ending …" (aria-busy) | Notice role=alert in the panel | todo | T07 |
| A11 | `PUT /api/inputs/weekly/{week}/{slot}?filename=` | the file as the body, `application/octet-stream` | Upload, Replace, Upload reports (several files, one request each) | every control in the panel disabled | Notice role=alert: "<file name>: <the API's reason>", one per refused file, joined by a space | todo | T07 |
| A12 | `DELETE /api/inputs/weekly/{week}/{stored_name}` | none | Remove | controls disabled | Notice role=alert | todo | none (N1) |
| A13 | `POST /api/inputs/weekly/{week}/cbk_bulletin/fetch` | none | "Fetch from CBK" (only while the slot is empty) | controls disabled | Notice role=alert | todo | none (N1) |
| A14 | `PUT /api/inputs/weekly/{week}/notes` | `{bidding_range}` or `{previous_issue}` | on blur, only when changed | controls disabled | Notice role=alert | todo | none (N1) |
| A15 | `GET /api/inputs/weekly/{week}/analyst?section=` | none | analyst panel; re-read when uploads change | "Reading the form…" (aria-busy) | Notice role=alert (pre-line) | todo | T08 |
| A16 | `PUT …/analyst?section=` | `{fields}`, `{tables: {key: {text} or {rows} or null}}`, or `{confirm: [key]}` | field on blur or Enter, table Save, Clear, Confirm | every control in the panel disabled | Notice role=alert, `white-space: pre-line`, every reason on its own line; nothing stored; what was typed stays in the field | todo | T08 |
| A17 | `POST …/analyst/carry?section=` | none | "Start from last week's form" (disabled unless `can_carry`) | controls disabled | Notice role=alert | todo | none (N2) |
| A18 | `POST …/analyst/suggest/{field}?section=` | none | "Suggest from last week's total" | controls disabled | Notice role=alert | todo | none (N2) |
| A19 | `GET /api/export/weekly?period=` | none | export bar; re-read when any section's run or decision changes | bar hidden until it answers | Notice role=alert in the bar | todo | T03, T14 |
| A20 | `POST /api/export/weekly?period=` | none; answer is the .docx | "Export weekly report" | button "Preparing…" | Notice role=alert (409 names each section) | todo | T14 |

## 4. Client state

| # | State | Where it lives | Vue | Test |
| --- | --- | --- | --- | --- |
| S1 | Phase of `/overview` (booting, unreachable, overview, start, review) and the chosen report (type, period, kind); nothing else is remembered, the server holds every review | `review-app.tsx` | todo | T03, T06, T09 |
| S2 | The report in the address bar, written with `history.replaceState` (no history entry) | `review-app.tsx` `reportToUrl` | todo | T04 |
| S3 | Back target and the leave question: one module-level store the page writes and the top bar reads | `lib/nav.ts` | todo | T06, T08 |
| S4 | Theme: `<html data-theme>` (absent means System); `localStorage["cytonn-theme"]` only remembers it, every access in try/catch | `lib/theme.ts` | todo | T05 |
| S5 | One open review kept in step with the server: one in-order write queue, saving count, save error, decision error, deciding | `hooks/use-review-session.ts` | todo | T09, T12 |
| S6 | Per item: the pending resolution while its write is in flight (only the newest write clears it); the note draft, dirty flag and last server note | `review-item-card.tsx` | todo | T12 |
| S7 | Items groups open or closed (Clean starts closed) | `items-pane.tsx` | todo | T12 |
| S8 | Report picker draft (type, period, kind), error, busy; reset when the report on screen changes (keyed) | `report-picker.tsx` | todo | T04 |
| S9 | Start screen: topic, text, starting flag, error with `lostConnection`, uploads counter, `typedPending`, the server's running draft and whether it is this section's | `start-screen.tsx` | todo | T08, T09 |
| S10 | Inputs panel: status, busy, error, picked date, the two notes; reset per week (keyed) | `inputs-panel.tsx` | todo | T07 |
| S11 | Analyst panel: form, error, busy, dirty map per item; each item keyed on what the API holds, so a refused save keeps what was typed and a kept one re-reads it | `analyst-panel.tsx` | todo | T08 |
| S12 | Run view: run, events merged by seq, missing, feed (connecting, stream, poll, lost), config, following-the-foot flag | `run-view.tsx` | todo | T12 |
| S13 | Export bar: status, busy, error | `export-bar.tsx` | todo | T14 |
| S14 | Drafting poll every 5 s while `drafting` is non-null; elapsed seconds counted on locally between polls | `drafting.tsx` | todo | none (N3) |

Pinia is not used: S3 and S4 are two small module-level stores, as in the Next app, and everything else is component state.

## 5. Behaviours that are easy to miss

| # | Behaviour | Next source | Vue | Test |
| --- | --- | --- | --- | --- |
| B1 | Top bar is sticky at the top of every page (44px, `--topbar-h`), above the masthead | `top-bar.tsx` | todo | T06 |
| B2 | Home goes to `/`; on `/` it carries `aria-current="page"` | `top-bar.tsx` | todo | T01, T06 |
| B3 | Back goes to the page's logical parent: start screen, open review and run view go to the report's list of sections ("Back to all sections"); the overview goes Home ("Back to Home"); on `/` it is disabled, not hidden ("Back (this is the start screen)") | `lib/nav.ts`, `review-app.tsx`, `run-view.tsx` | todo | T01, T04, T06, T09 |
| B4 | Home and Back ask first (`window.confirm`) while something typed on the analyst form is unsaved: "Something typed under "Weekly analyst inputs" is not saved yet. Leave this page and lose it?"; Cancel stays | `lib/nav.ts` `useLeaveGuard`, `mayLeave` | todo | T08 |
| B5 | The browser's own leave prompt (`beforeunload`) while a review item's note is typed and not yet committed | `review-item-card.tsx` | todo | T12 |
| B6 | Theme toggle: Light, Dark, System as one radio group (one tab stop, arrow keys), the choice shown by filled icon, framed box, the word beside it from `sm` up, and the group's name "Theme: Dark" | `theme-toggle.tsx` | todo | T05, T16 |
| B7 | Theme restored by an inline script before the first paint; System clears storage; storage that throws is ignored | `lib/theme.ts`, `layout.tsx` | todo | T05 |
| B8 | Review status bar is sticky under the top bar (and under the dev ribbon when there is one): unresolved count, "N of M resolved", "Saving…" / "Not saved" / "Saved as run N", the approvability message, Approve and Reject | `status-bar.tsx` | todo | T09, T12 |
| B9 | Approve is disabled until `is_approvable`; Reject is always allowed; each asks in a dialog; a decision is final: afterwards the bar shows "Decision recorded: approved." and "Back to all sections", the LockBar shows, every control is locked | `decision-controls.tsx`, `banners.tsx` | todo | T09 |
| B10 | Dialog cannot be dismissed while the decision is being recorded; it has no close button; Escape and the overlay close it otherwise | `decision-controls.tsx` | todo | T09 |
| B11 | Review items grouped Flagged, Not auto-verified, Clean with counts; states shown by shape as well as colour (glyphs `!`, `?`, `✓`, solid bar, dashed outline, hairline) | `items-pane.tsx`, `globals.css` | todo | T12 |
| B12 | Resolution control: Unresolved, Accept, Fix needed as a radio group; the click shows at once, writes queue in order | `resolution-control.tsx`, `review-item-card.tsx` | todo | T09, T12 |
| B13 | Note box: saved on blur or Enter (Shift+Enter is a new line), only when changed; read-only when locked; a server refresh never overwrites typing | `review-item-card.tsx` | todo | T12 |
| B14 | Analyst form: a field saves when the cursor leaves it (Enter blurs); a table has its own Save, "Discard changes", "Clear typed table/values", "Not saved yet." | `analyst-panel.tsx` | todo | T08 |
| B15 | Analyst form save is all or nothing; every refusal reason is listed, one a line; the typed value stays | `analyst-panel.tsx`, API | todo | T08 |
| B16 | The draft button is disabled while anything on the analyst form is unsaved, being saved, refused, or waiting to be confirmed, with "Something under "Weekly analyst inputs" is not saved yet…" | `start-screen.tsx` | todo | T08 |
| B17 | Analyst item chips: Typed / Typed, differs from the workbook / From the workbook / Empty / Carried from week ending … / … not confirmed; workbook value as placeholder; rows in use under a table; carried cells dashed and shaded | `analyst-panel.tsx` | todo | T08 (chips), none for carried (N2) |
| B18 | Upload: the hidden file input is reset so the same file can be chosen again after a refusal; a refused file shows "<name>: <reason>" | `inputs-panel.tsx` | todo | T07 |
| B19 | Week picker: a date that is not a Friday shows "<date> is a <weekday>; a weekly report's week ends on a Friday." and disables "Show this week" | `inputs-panel.tsx` | todo | T07 |
| B20 | Draft button also disabled while starting, while another draft holds the slot (unless stale), when the provider has a problem, when the topic or text is missing, when the topic is over 500 characters (counted as the API counts) | `start-screen.tsx`, `lib/topic.ts` | todo | T09 (text), none for the rest (N3) |
| B21 | Run view shows only real events: a "started" line is replaced in place by its closing event; the spinner is on the latest open step only; no timers | `lib/run.ts`, `run-view.tsx` | todo | T12 |
| B22 | Run view never navigates by itself: a finished run shows the three counts and "Open review"; a failed one "The draft stopped. <error>" and "Back to overview"; an unknown run says so | `run-view.tsx` | todo | T09, T11, T15 |
| B23 | DEV MODE ribbon (fixed under the top bar) on the overview, start screen, run view and a dev review; DEV MODE notices; DEV DRAFT chip on a section card | `banners.tsx` and callers | todo | T03, T12 |
| B24 | Run view follows the newest line only for someone already within 96px of the foot of the page | `run-view.tsx` | todo | none (N4) |
| B25 | Word export: enabled only when the API says every section is approved; downloads the blob under the name in `Content-Disposition` (fallback "Cytonn-Weekly.docx"); per-section chips | `export-bar.tsx`, `lib/api.ts` | todo | T03, T14 |
| B26 | Keyboard and focus: skip link "Skip to main content" is the first tab stop and targets `#main`; `main` is focusable (`tabindex=-1`) with no outline; scroll-padding keeps focused things clear of the sticky bars; data tables and row previews are focusable scroll regions; every control has a visible focus ring | `layout.tsx`, `globals.css` | todo | T16 |
| B27 | Touch: pressable controls reach 44px on coarse pointers; press feedback scale(0.97) unless reduced motion | `globals.css` | todo | none (CSS reused as is) |
| B28 | Reduced motion: transitions and animations cut to nothing; spinners do not spin | `globals.css`, `run-view.tsx` | todo | none (N4) |
| B29 | Landing greeting appears only once the page is live in the browser; never a wrong one | `landing-page.tsx` | todo | T01 |
| B30 | Links in drafted text and sources open in a new tab with `rel="noopener noreferrer"`; only http(s) source URLs are linked; raw HTML in markdown is not rendered | `markdown.tsx`, `blocks-pane.tsx`, `review-item-card.tsx` | todo | none (N5) |
| B31 | Screen transitions: the phase fades and rises 6px (0.18 s); list items, notices and chips fade in; the resolution thumb slides; the progress bar eases | `motion` in many components | todo | none (N4) |

## 6. User-visible strings

Every string is ported verbatim from the Next component named in section 2 (curly apostrophes and quotes, "…", "·"
included). The fixed wording that lives outside components: run step templates (`lib/run.ts`), status and kind labels
(`lib/format.ts`), the API error fallbacks (`lib/api.ts`), the leave question (`analyst-panel.tsx`), the page title and
description (`layout.tsx`). `lib/run.ts`, `lib/format.ts`, `lib/topic.ts`, `lib/types.ts` and `lib/sso.ts` are copied
file for file. `scripts/check-copy.mjs` compares the text of the two source trees; see section 8 for its result.

| # | Strings | Vue | Check |
| --- | --- | --- | --- |
| X1 | Component copy (sections 2's files) | todo | `npm run check:copy` |
| X2 | `lib/` wording (run steps, labels, errors) | todo | files copied; Vitest for `run.ts`, `format.ts`, `topic.ts` |
| X3 | The one string that names the framework: the Unreachable screen's "To point this app at another address, set NEXT_PUBLIC_API_URL." | todo | differs by design (N6) |

## 7. Notes on what is not tested automatically

- **N1** Remove, Fetch from CBK and the notes boxes change the stored week and (the fetch) reach centralbank.go.ke; the suite leaves them alone so a run stays repeatable offline of CBK's site. Ported and checked by hand.
- **N2** Carry forward, suggestions and confirmation need a saved previous week; the demo data holds one week only. Ported from the source line by line; not exercised.
- **N3** A second draft holding the slot, a stale draft, a provider problem and the Focus topic limit need server states the demo instance does not produce on demand. Ported; not exercised.
- **N4** Scroll following, reduced motion and animation timing are not reliably testable end to end; compared by eye.
- **N5** Markdown safety is covered by a Vitest unit test in the Vue app, not by the shared suite (the Next app has no unit tests).
- **N6** See section 8.

## 8. Results

Filled in at the end of the port: see the summary at the foot of this file.
