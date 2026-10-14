# Parity checklist: the Next.js app to the Vue 3 app in frontend/

The checklist the Vue app was built against, kept as a record of 2026-10-13. **The Next.js reference was removed at
the cut-over commit ("Remove the Next.js frontend"), when `frontend-vue/` was renamed to `frontend/`; it can be
recovered from the local git tag `last-next-frontend`.** One row per thing the
Next app did. **Vue** is the state of the port: `todo`, `done` (ported, checked by hand or by typecheck only), or
`verified by Tn` (test `Tn` of `e2e/tests/app.spec.ts` passes against both apps). **Test** names the test that covers
the behaviour on the Next app; `none` means no automated test, with the reason in the notes at the foot.

"Next source" paths are under `src/` of the Next app at that tag; Vue paths are under `frontend/src/`.

## 1. Routes and pages

| # | Route | What it shows | Next source | Vue | Test |
| --- | --- | --- | --- | --- | --- |
| R1 | `/` | Landing page: greeting by the viewer's clock, "Ready" line, disabled SSO button, "Continue without signing in", no-sign-in notice. Makes no API call. | `app/page.tsx`, `components/landing/landing-page.tsx` | verified by T01 | T01 |
| R2 | `/?report=`, `?period=`, `?kind=` | Old bookmark: redirects to `/overview` with the whole query string kept | `app/page.tsx` | verified by T02 | T02 |
| R3 | `/overview` | Phase machine: booting, unreachable, overview, start, review. Report mirrored in the address bar (`?report=&period=&kind=`), absent means weekly; a report the API rejects (422) falls back to weekly | `app/overview/page.tsx`, `components/review/review-app.tsx` | verified by T03, T04 | T03, T04 |
| R4 | `/overview?review=<id>` | Opens that saved review directly; if it cannot be read, the overview | `review-app.tsx` (`reviewFromUrl`, `boot`) | verified by T09 | T09 |
| R5 | `/runs/:runId` | The draft run view | `app/runs/[runId]/page.tsx`, `components/run/run-view.tsx` | verified by T09, T11, T12, T15 | T09, T11, T12, T15 |
| R6 | every page | Root layout: `<html lang="en">`, title "Cytonn Weekly review", description, theme-color metas (#0a2b29 light, #0e2421 dark), the two fonts, skip link, top bar | `app/layout.tsx` | verified by T16 | T16 |

## 2. Components

| # | Component | Next source | Vue file | Vue |
| --- | --- | --- | --- | --- |
| C1 | TopBar (Home, Back, theme) | `components/nav/top-bar.tsx` | `components/nav/TopBar.vue` | done |
| C2 | ThemeToggle (radio group of three) | `components/nav/theme-toggle.tsx` | `components/nav/ThemeToggle.vue` | done |
| C3 | LandingPage | `components/landing/landing-page.tsx` | `pages/LandingPage.vue` | done |
| C4 | ReviewApp (phase machine, Booting, Unreachable) | `components/review/review-app.tsx` | `pages/OverviewPage.vue` | done |
| C5 | Masthead | `components/review/masthead.tsx` | `components/review/Masthead.vue` | done |
| C6 | Notice, DevRibbon, DevAlert, LockBar | `components/review/banners.tsx` | `components/review/Notice.vue`, `DevRibbon.vue`; DevAlert is a Notice at each use, LockBar is in `ReviewScreen.vue` | done |
| C7 | OverviewScreen (StateChip, Progress, SectionRow, Tally) | `components/review/overview-screen.tsx` | `components/review/OverviewScreen.vue`, `SectionRow.vue` | done |
| C8 | ReportPicker | `components/review/report-picker.tsx` | `components/review/ReportPicker.vue` | done |
| C9 | Drafting poll, live elapsed, DraftingBanner, DraftingChip | `components/review/drafting.tsx` | `lib/drafting.ts`, `components/review/DraftingBanner.vue`; the chip is in `SectionRow.vue` | done |
| C10 | ExportBar | `components/review/export-bar.tsx` | `components/review/ExportBar.vue` | done |
| C11 | StartScreen (ServerDraftingNotice, FromTheReport) | `components/review/start-screen.tsx` | `components/review/StartScreen.vue` | done |
| C12 | InputsPanel (StateChip, FileLine, Slot) | `components/review/inputs-panel.tsx` | `components/review/InputsPanel.vue`, `InputSlot.vue`, `ToneChip.vue` | done |
| C13 | AnalystPanel (OriginChip, Provenance, Differences, Confirm, FieldRow, RowsPreview, TableHead, TableNotes, PasteTable, GridTable) | `components/review/analyst-panel.tsx` | `components/review/analyst/` (`AnalystPanel`, `FieldRow`, `PasteTable`, `GridTable`, `TableFrame`, `ConfirmBox`, `Differences`, `OriginChip`, `SourceLine`), `lib/analyst.ts` | done |
| C14 | ReviewScreen | `components/review/review-screen.tsx` | `components/review/ReviewScreen.vue` | done |
| C15 | StatusBar (Message) | `components/review/status-bar.tsx` | `components/review/StatusBar.vue` | done |
| C16 | DecisionControls (confirm dialog) | `components/review/decision-controls.tsx`, `components/ui/dialog.tsx` | `components/review/DecisionControls.vue` (Reka Dialog) | done |
| C17 | Scorecard, CountTile | `components/review/scorecard.tsx`, `run-view.tsx` | `components/review/CountTile.vue`; the scorecard row is in `ReviewScreen.vue` | done |
| C18 | DraftPane (Numeral, Warnings, Highlight, DataTable, StockTable, OutlookBlock) | `components/review/draft-pane.tsx` | `components/review/DraftPane.vue`, `DataTable.vue`, `Numeral.vue`, `Warnings.vue`, `PartsLine.vue` | done |
| C19 | BlocksPane (Narrative, Table, Computed, Carried, Unavailable, Supplied, ChartNotes, NotCoveredNotes, summary) | `components/review/blocks-pane.tsx` | `components/review/BlocksPane.vue` | done |
| C20 | ItemsPane (collapsible groups, accept-clean) | `components/review/items-pane.tsx`, `components/ui/collapsible.tsx` | `components/review/ItemsPane.vue` (Reka Collapsible) | done |
| C21 | ReviewItemCard (FlagDetail, Detail, note box) | `components/review/review-item-card.tsx` | `components/review/ReviewItemCard.vue` | done |
| C22 | ResolutionControl (segmented radio group) | `components/review/resolution-control.tsx` | `components/review/ResolutionControl.vue` (Reka RadioGroup) | done |
| C23 | Markdown (no raw HTML, safe links, new tab) | `components/review/markdown.tsx` | `components/review/Markdown.vue`, `lib/markdown.ts` (markdown-it, `html: false`) | done |
| C24 | RunView (Mark, Step, CountTile, Shell) | `components/run/run-view.tsx` | `pages/RunPage.vue` | done |
| C25 | Button (variants and sizes), Skeleton, Textarea | `components/ui/button.tsx`, `skeleton.tsx`, `textarea.tsx` | `components/ui/Button.vue`, `button.ts`, `Textarea.vue`; the skeleton is plain divs in `OverviewPage.vue` | done |

## 3. Backend calls

All through `lib/api.ts` (`request()`): JSON, `cache: "no-store"`, a 30 s timeout (180 s for uploads, form saves, carry,
suggest, bulletin fetch). Errors become `ApiError(message, status)`: the API's `detail` string, or FastAPI's validation
list joined with "; ", or "<status> <statusText>"; `status` is null when no answer arrived ("Could not reach the review
API at <base>. Is it running?" or "The request timed out after N seconds."). In the Vue app the base is the page's own
origin and Vite proxies `/api` to the backend, so the "could not reach" message names the page's origin.

| # | Call | Payload | Where | Loading shown as | Error shown as | Vue | Test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `GET /api/config` | none | overview boot, start screen, run view | Booting skeleton (overview) | Unreachable screen with the message and "Try again"; ignored on the run view | verified by T03 | T03 |
| A2 | `GET /api/sections?report_type=&period=&kind=` | query | overview, start screen, the 5 s drafting poll, after a 409 on draft | Booting skeleton; picker button "Loading…" | 422 under the picker's period (role=alert); on boot a 422 falls back to weekly; other errors: Unreachable; a failed poll is retried silently | verified by T03, T04 | T03, T04 |
| A3 | `POST /api/runs` | `{section, report_type, period or null, kind, topic?, text?, provider?}` | start screen draft button | Button "Starting…", inputs disabled | Notice role=alert with the API's message; "Check for a saved draft" when status is null or 409 | verified by T09, T11, T12 | T09, T11, T12 |
| A4 | `GET /api/runs/{id}` | none | run view: first read, 2 s poll, once after the last event | "Loading the run…" | 404: "This run is no longer available…"; other failure: "Not connected." and the Connection lost notice | verified by T09, T15 | T09, T15 |
| A5 | `GET /api/runs/{id}/events` (EventSource, event `step`) | none | run view | status line "Running. Started …" | on error the source is closed for good: `poll` ("Live updates are off; checking every 2 seconds.") if it never opened, `lost` ("Connection lost. …") if it dropped | verified by T12 | T12 |
| A6 | `GET /api/reviews/{id}` | none | resume, `?review=`, re-sync after a failed write | Booting skeleton | Unreachable screen (resume); overview (deep link) | verified by T09 | T09 |
| A7 | `PATCH /api/reviews/{id}/items/{index}` | `{resolution}` or `{resolution, note}` | resolution control, note box on blur or Enter | status bar "Saving…"; the control shows the pending choice at once | status bar "Not saved" and "NOT SAVED: … The last change did not reach the server; the screen shows what the server holds."; review re-read | verified by T09, T12 | T09, T12 |
| A8 | `POST /api/reviews/{id}/accept-clean` | none | "Mark all clean as accepted (N unresolved)" | "Saving…" | as A7 | verified by T12 | T12 |
| A9 | `POST /api/reviews/{id}/decide` | `{decision}` | confirm dialog | dialog button "Recording…", buttons disabled | Notice role=alert in the status bar; review re-read | verified by T09 | T09 |
| A10 | `GET /api/inputs/weekly/{week}` | none | inputs panel | "Reading what has been received for the week ending …" (aria-busy) | Notice role=alert in the panel | verified by T07 | T07 |
| A11 | `PUT /api/inputs/weekly/{week}/{slot}?filename=` | the file as the body, `application/octet-stream` | Upload, Replace, Upload reports (several files, one request each) | every control in the panel disabled | Notice role=alert: "<file name>: <the API's reason>", one per refused file, joined by a space | verified by T07 | T07 |
| A12 | `DELETE /api/inputs/weekly/{week}/{stored_name}` | none | Remove | controls disabled | Notice role=alert | verified by T17 | T17 |
| A13 | `POST /api/inputs/weekly/{week}/cbk_bulletin/fetch` | none | "Fetch from CBK" (only while the slot is empty) | controls disabled | Notice role=alert | verified by T17 | T17 |
| A14 | `PUT /api/inputs/weekly/{week}/notes` | `{bidding_range}` or `{previous_issue}` | on blur, only when changed | controls disabled | Notice role=alert | verified by T17 | T17 |
| A15 | `GET /api/inputs/weekly/{week}/analyst?section=` | none | analyst panel; re-read when uploads change | "Reading the form…" (aria-busy) | Notice role=alert (pre-line) | verified by T08 | T08 |
| A16 | `PUT …/analyst?section=` | `{fields}`, `{tables: {key: {text} or {rows} or null}}`, or `{confirm: [key]}` | field on blur or Enter, table Save, Clear, Confirm | every control in the panel disabled | Notice role=alert, `white-space: pre-line`, every reason on its own line; nothing stored; what was typed stays in the field | verified by T08 | T08 |
| A17 | `POST …/analyst/carry?section=` | none | "Start from last week's form" (disabled unless `can_carry`, which since 2026-10-14 counts only what last week confirmed, as the carry itself does) | controls disabled | Notice role=alert | verified by T19, T28 to T30 | T19, T28 to T30 |
| A18 | `POST …/analyst/suggest/{field}?section=` | none | "Suggest from last week's total" | controls disabled | role=alert under that field, named in its `aria-describedby` (since 2026-10-14; the Next app showed it at the top of the panel) | verified by T20, T31 to T33 | T20, T31 to T33 |
| A19 | `GET /api/export/weekly?period=` | none | export bar; re-read when any section's run or decision changes | bar hidden until it answers | Notice role=alert in the bar | verified by T03, T14 | T03, T14 |
| A20 | `POST /api/export/weekly?period=` | none; answer is the .docx | "Export weekly report" | button "Preparing…" | Notice role=alert (409 names each section) | verified by T14 | T14 |

## 4. Client state

| # | State | Where it lives | Vue | Test |
| --- | --- | --- | --- | --- |
| S1 | Phase of `/overview` (booting, unreachable, overview, start, review) and the chosen report (type, period, kind); nothing else is remembered, the server holds every review | `review-app.tsx` | verified by T03, T06, T09 | T03, T06, T09 |
| S2 | The report in the address bar, written with `history.replaceState` (no history entry) | `review-app.tsx` `reportToUrl` | verified by T04 | T04 |
| S3 | Back target and the leave question: one module-level store the page writes and the top bar reads | `lib/nav.ts` | verified by T06, T08 | T06, T08 |
| S4 | Theme: `<html data-theme>` (absent means System); `localStorage["cytonn-theme"]` only remembers it, every access in try/catch | `lib/theme.ts` | verified by T05 | T05 |
| S5 | One open review kept in step with the server: one in-order write queue, saving count, save error, decision error, deciding | `hooks/use-review-session.ts` (Vue: `lib/session.ts`) | verified by T09, T12 | T09, T12 |
| S6 | Per item: the pending resolution while its write is in flight (only the newest write clears it); the note draft, dirty flag and last server note | `review-item-card.tsx` | verified by T12 | T12 |
| S7 | Items groups open or closed (Clean starts closed) | `items-pane.tsx` | verified by T12 | T12 |
| S8 | Report picker draft (type, period, kind), error, busy; reset when the report on screen changes (keyed) | `report-picker.tsx` | verified by T04 | T04 |
| S9 | Start screen: topic, text, starting flag, error with `lostConnection`, uploads counter, `typedPending`, the server's running draft and whether it is this section's | `start-screen.tsx` | verified by T08, T09 | T08, T09 |
| S10 | Inputs panel: status, busy, error, picked date, the two notes; reset per week (keyed) | `inputs-panel.tsx` | verified by T07 | T07 |
| S11 | Analyst panel: form, error, busy, dirty map per item; each item keyed on what the API holds, so a refused save keeps what was typed and a kept one re-reads it | `analyst-panel.tsx` | verified by T08 | T08 |
| S12 | Run view: run, events merged by seq, missing, feed (connecting, stream, poll, lost), config, following-the-foot flag | `run-view.tsx` | verified by T12 | T12 |
| S13 | Export bar: status, busy, error | `export-bar.tsx` | verified by T14 | T14 |
| S14 | Drafting poll every 5 s while `drafting` is non-null; elapsed seconds counted on locally between polls | `drafting.tsx` | verified by T24, T27 | T24, T27 |

Pinia is not used: S3 and S4 are two small module-level stores, as in the Next app, and everything else is component state.

## 5. Behaviours that are easy to miss

| # | Behaviour | Next source | Vue | Test |
| --- | --- | --- | --- | --- |
| B1 | Top bar is sticky at the top of every page (44px, `--topbar-h`), above the masthead | `top-bar.tsx` | verified by T06 | T06 |
| B2 | Home goes to `/`; on `/` it carries `aria-current="page"` | `top-bar.tsx` | verified by T01, T06 | T01, T06 |
| B3 | Back goes to the page's logical parent: start screen, open review and run view go to the report's list of sections ("Back to all sections"); the overview goes Home ("Back to Home"); on `/` it is disabled, not hidden ("Back (this is the start screen)") | `lib/nav.ts`, `review-app.tsx`, `run-view.tsx` | verified by T01, T04, T06, T09 | T01, T04, T06, T09 |
| B4 | Home and Back ask first (`window.confirm`) while something typed on the analyst form is unsaved: "Something typed under "Weekly analyst inputs" is not saved yet. Leave this page and lose it?"; Cancel stays | `lib/nav.ts` `useLeaveGuard`, `mayLeave` | verified by T08 | T08 |
| B5 | The browser's own leave prompt (`beforeunload`) while a review item's note is typed and not yet committed | `review-item-card.tsx` | verified by T12 | T12 |
| B6 | Theme toggle: Light, Dark, System as one radio group (one tab stop, arrow keys), the choice shown by filled icon, framed box, the word beside it from `sm` up, and the group's name "Theme: Dark" | `theme-toggle.tsx` | verified by T05, T16 | T05, T16 |
| B7 | Theme restored by an inline script before the first paint; System clears storage; storage that throws is ignored | `lib/theme.ts`, `layout.tsx` | verified by T05 | T05 |
| B8 | Review status bar is sticky under the top bar (and under the dev ribbon when there is one): unresolved count, "N of M resolved", "Saving…" / "Not saved" / "Saved as run N", the approvability message, Approve and Reject | `status-bar.tsx` | verified by T09, T12 | T09, T12 |
| B9 | Approve is disabled until `is_approvable`; Reject is always allowed; each asks in a dialog; a decision is final: afterwards the bar shows "Decision recorded: approved." and "Back to all sections", the LockBar shows, every control is locked | `decision-controls.tsx`, `banners.tsx` | verified by T09 | T09 |
| B10 | Dialog cannot be dismissed while the decision is being recorded; it has no close button; Escape and the overlay close it otherwise | `decision-controls.tsx` | verified by T09 | T09 |
| B11 | Review items grouped Flagged, Not auto-verified, Clean with counts; states shown by shape as well as colour (glyphs `!`, `?`, `✓`, solid bar, dashed outline, hairline) | `items-pane.tsx`, `globals.css` | verified by T12 | T12 |
| B12 | Resolution control: Unresolved, Accept, Fix needed as a radio group; the click shows at once, writes queue in order | `resolution-control.tsx`, `review-item-card.tsx` | verified by T09, T12 | T09, T12 |
| B13 | Note box: saved on blur or Enter (Shift+Enter is a new line), only when changed; read-only when locked; a server refresh never overwrites typing | `review-item-card.tsx` | verified by T12 | T12 |
| B14 | Analyst form: a field saves when the cursor leaves it (Enter blurs); a table has its own Save, "Discard changes", "Clear typed table/values", "Not saved yet." | `analyst-panel.tsx` | verified by T08 | T08 |
| B15 | Analyst form save is all or nothing; every refusal reason is listed, one a line; the typed value stays | `analyst-panel.tsx`, API | verified by T08 | T08 |
| B16 | The draft button is disabled while anything on the analyst form is unsaved, being saved, refused, or waiting to be confirmed, with "Something under "Weekly analyst inputs" is not saved yet…" | `start-screen.tsx` | verified by T08 | T08 |
| B17 | Analyst item chips: Typed / Typed, differs from the workbook / From the workbook / Empty / Carried from week ending … / … not confirmed; workbook value as placeholder; rows in use under a table; carried cells dashed and shaded | `analyst-panel.tsx` | verified by T08, T18, T19, T20 | T08, T18, T19, T20 |
| B18 | Upload: the hidden file input is reset so the same file can be chosen again after a refusal; a refused file shows "<name>: <reason>" | `inputs-panel.tsx` | verified by T07 | T07 |
| B19 | Week picker: a date that is not a Friday shows "<date> is a <weekday>; a weekly report's week ends on a Friday." and disables "Show this week" | `inputs-panel.tsx` | verified by T07 | T07 |
| B20 | Draft button also disabled while starting, while another draft holds the slot (unless stale), when the provider has a problem, when the topic or text is missing, when the topic is over 500 characters (counted as the API counts) | `start-screen.tsx`, `lib/topic.ts` | verified by T09, T21, T24, T26 | T09, T21, T24, T26 |
| B21 | Run view shows only real events: a "started" line is replaced in place by its closing event; the spinner is on the latest open step only; no timers | `lib/run.ts`, `run-view.tsx` | verified by T12 | T12 |
| B22 | Run view never navigates by itself: a finished run shows the three counts and "Open review"; a failed one "The draft stopped. <error>" and "Back to overview"; an unknown run says so | `run-view.tsx` | verified by T09, T11, T15 | T09, T11, T15 |
| B23 | DEV MODE ribbon (fixed under the top bar) on the overview, start screen, run view and a dev review; DEV MODE notices; DEV DRAFT chip on a section card | `banners.tsx` and callers | verified by T03, T12 | T03, T12 |
| B24 | Run view follows the newest line only for someone already within 96px of the foot of the page | `run-view.tsx` | done | none (N4) |
| B25 | Word export: enabled only when the API says every section is approved; downloads the blob under the name in `Content-Disposition` (fallback "Cytonn-Weekly.docx"); per-section chips | `export-bar.tsx`, `lib/api.ts` | verified by T03, T14 | T03, T14 |
| B26 | Keyboard and focus: skip link "Skip to main content" is the first tab stop and targets `#main`; `main` is focusable (`tabindex=-1`) with no outline; scroll-padding keeps focused things clear of the sticky bars; data tables and row previews are focusable scroll regions; every control has a visible focus ring | `layout.tsx`, `globals.css` | verified by T16 | T16 |
| B27 | Touch: pressable controls reach 44px on coarse pointers; press feedback scale(0.97) unless reduced motion | `globals.css` | done | none (CSS reused as is) |
| B28 | Reduced motion: transitions and animations cut to nothing; spinners do not spin | `globals.css`, `run-view.tsx` | done | none (N4) |
| B29 | Landing greeting appears only once the page is live in the browser; never a wrong one | `landing-page.tsx` | verified by T01 | T01 |
| B30 | Links in drafted text and sources open in a new tab with `rel="noopener noreferrer"`; only http(s) source URLs are linked; raw HTML in markdown is not rendered | `markdown.tsx`, `blocks-pane.tsx`, `review-item-card.tsx` | verified by T22 | T22 |
| B31 | Screen transitions: the phase fades and rises 6px (0.18 s); list items, notices and chips fade in; the resolution thumb slides; the progress bar eases | `motion` in many components | done | none (N4) |

| B32 | Reject: allowed with nothing resolved; asks in a dialog ("Reject this section?"); afterwards "Rejected and locked", "Decision recorded: rejected.", every control locked; the overview card reads Rejected with "View review" and the export chip says so | `decision-controls.tsx`, `banners.tsx`, `overview-screen.tsx` | verified by T23 | T23 |
| B33 | The weekly Digital Payments review shape: highlights under roman numerals with their provenance line, the stock table with its eight weekly columns, the outlook with its stats, and the item kinds Table row, Outlook stat, Highlight claim | `draft-pane.tsx` | verified by T22 | T22 |
| B34 | A draft holding the one draft slot: banner and "Drafting now" chip on the overview; on another drafting section's start screen "<title> is drafting now (…)" and the draft button off; on its own section "This section is drafting now"; a section that calls no provider is not blocked; the waiting screen unlocks on its next poll | `drafting.tsx`, `start-screen.tsx`, `overview-screen.tsx` | verified by T24 | T24 |
| B35 | A stale draft: "…has been drafting for …, longer than any healthy draft takes. It looks stuck", chip "Looks stuck", the draft button stays on, the next draft takes the slot over and the stuck run ends as stopped | `drafting.tsx`, `start-screen.tsx` | verified by T27 | T27 |
| B36 | A provider problem: the API's own sentence and "Drafting is off until then." on the start screen of every drafting section, the draft button off, Enter in the topic box does nothing; no budget notice; a section that calls no provider still works. It never reaches the run view: no run starts (the API answers 409 in the same words) | `start-screen.tsx` | verified by T26 | T26 |
| B37 | Executive Summary: composing before every section is approved stops the run with the API's list of sections still to approve; once all are approved the review shows the summary note and the "Not covered by this summary" panel (Tables, Parts not yet drafted, Further pieces, per section with its run) | `start-screen.tsx`, `blocks-pane.tsx` | verified by T25 | T25 |

## 6. User-visible strings

Every string is ported verbatim from the Next component named in section 2 (curly apostrophes and quotes, "…", "·"
included). The fixed wording that lives outside components: run step templates (`lib/run.ts`), status and kind labels
(`lib/format.ts`), the API error fallbacks (`lib/api.ts`), the leave question (`analyst-panel.tsx`), the page title and
description (`layout.tsx`). `lib/run.ts`, `lib/format.ts`, `lib/topic.ts`, `lib/types.ts` and `lib/sso.ts` are copied
file for file. `scripts/check-copy.mjs` compared the text of the two source trees (removed at the cut-over, with the tree it read);
see section 8 for its result.

| # | Strings | Vue | Check |
| --- | --- | --- | --- |
| X1 | Component copy (sections 2's files) | done | the copy check (removed at the cut-over) |
| X2 | `lib/` wording (run steps, labels, errors) | done | files copied; Vitest for `run.ts`, `format.ts`, `topic.ts` |
| X3 | The one string that names the framework: the Unreachable screen's "To point this app at another address, set …", which named the Next app's own setting | done | differs by design (N6) |

## 7. Notes on what is not tested automatically

- **N1 to N3** (inputs removal, Fetch from CBK, the notes boxes, carry forward, suggestions, a held or stale draft slot, a provider problem, the Focus topic limit) were not tested in the first pass. They are now: T17 to T27.
- **N4** Scroll following, reduced motion and animation timing are not reliably testable end to end; compared by eye.
- **N5** Markdown safety is covered by Vitest unit tests in the Vue app (`src/lib/lib.test.ts`); T22 checks that a drafted link opens in a new tab with `rel="noopener noreferrer"` in both apps.
- **N6** See section 8.

## 8. Results (2026-10-13)

**Summary.** 105 rows: 73 verified by a named end-to-end test that passes against both apps, 32 done (ported and
checked by typecheck, the copy check, unit tests or by eye, with no end-to-end test of their own: the component
rows, which are covered through the behaviours they carry, and N4 to N6). Nothing is left to do on the checklist; the known gaps are listed at the foot.

**The shared suite (`e2e/tests/app.spec.ts`, `more.spec.ts`, `variants.spec.ts`), final run against each app: 27 passed, 0 failed.** T01 to T16 and T17 to T25 run on the default test backend, each file on freshly restored data (a section that has a review no longer offers its start screen); T26 and T27 each need the backend started in another state (`npm run test:variants`), so each is skipped in the runs that are not its own.

| Test | What it covers | Next | Vue |
| --- | --- | --- | --- |
| T01 | Landing page loads, with Home current and Back disabled | pass | pass |
| T02 | An old bookmark of a report at `/` goes to the overview with its query kept | pass | pass |
| T03 | Overview lists the six weekly sections, the dev mark and the export gate | pass | pass |
| T04 | Report picker shows the API's refusal, switches report, keeps it on reload; Back from the overview goes Home | pass | pass |
| T05 | Theme toggle: Light, Dark, System, kept after a reload and applied before the first paint | pass | pass |
| T06 | Top bar stays in view after scrolling; Back goes to the section list, Home to `/` | pass | pass |
| T07 | Inputs panel: what was received, an upload refused with its reason, a week that is not a Friday | pass | pass |
| T08 | Analyst inputs: refusals listed, the draft button waits for unsaved typing, Home and Back ask first | pass | pass |
| T09 | Company Updates: run to done, open the review, Approve is gated, the decision is final | pass | pass |
| T10 | The sticky status bar stays under the top bar while a review scrolls | pass | pass |
| T11 | A stopped run shows the error text and the way back | pass | pass |
| T12 | Fixed Income: run view steps to done, review lists the three statuses, accepting, notes, the leave prompt | pass | pass |
| T13 | Equities: run to done and its review opens with items | pass | pass |
| T14 | Word export: off until every section is approved; when the API says ready, the file downloads under its name | pass | pass |
| T15 | A run the API no longer has says so and links to the overview | pass | pass |
| T16 | Keyboard: the skip link comes first, the theme group is one tab stop moved by arrow keys | pass | pass |
| T17 | Inputs: remove a report and upload it again, Fetch from CBK (answered from a saved file), the two notes boxes | pass | pass |
| T18 | Analyst inputs: a typed table is saved, shown as the rows in use, and cleared again | pass | pass |
| T19 | Analyst inputs: start from last week's form; a weekly figure waits to be confirmed | pass | pass |
| T20 | Analyst inputs: a running total is suggested from last week's, refused when there is none, and waits to be confirmed | pass | pass |
| T21 | Focus of the Week: the topic is counted as the API counts it and blocks the draft over 500 characters | pass | pass |
| T22 | Weekly Digital Payments: its own review shape (highlights, the stock table, the outlook) | pass | pass |
| T23 | Rejecting a section is final: the dialog, the locked review, the overview afterwards | pass | pass |
| T24 | A draft holding the one draft slot: the overview and the other sections say so, and unlock when it ends | pass | pass |
| T25 | Executive Summary: refused until every section is approved, then composed, with what it leaves out | pass | pass |
| T26 | A provider problem: said on the start screen, drafting is off, and the API refuses a run (variant `no-key`) | pass | pass |
| T27 | A stale draft: shown as stuck, the next draft takes the slot over and the stuck one's result is discarded (variant `stale`) | pass | pass |

How each app was run: the Next app as a production build (`next build`, `next start`) of the committed `frontend/`,
made in a copy outside the repository with the API's address set to `http://127.0.0.1:8011` at build time; the Vue app on Vite's dev
server with `/api` proxied to the same test API. No backend change was needed for either.

**Other checks on the Vue app:** `npm run typecheck` clean; `npm run lint` clean; `npm test` 16 passed;
the copy check 149 phrases checked, 0 missing; `npm run build` succeeds.

**Screenshots** (taken and compared by two scripts in `e2e/` that were removed at the cut-over): 20 pages and states of each app, each in light
and dark at 1280 px and 390 px (80 images an app, in `screenshots/parity/next` and `/vue`, not committed). The
script ranks the pairs by the share of pixels that differ; the most different were then looked at side by side.

- All 80 pairs are the same size, to the pixel, including the 50,000 px Fixed Income review. 72 of them differ in
  under 0.6% of pixels: the run's own data (timestamps, run numbers) and sub-pixel text position.
- The Fixed Income run view, finished, differs by up to 2.5% in its first shot. The page had scrolled to follow the
  newest step, and a full-page capture draws the sticky top bar where the page was scrolled to, which was about 30 px
  apart in the two apps at that moment. The page under it is the same.
- The landing page (and the two focus shots taken on it) differs by about 1% of pixels at 390 px and 0.4% at 1280 px:
  the same faces, but from `@fontsource` here and `next/font` there, so glyph edges fall on slightly different
  sub-pixels. Layout, line breaks and sizes are the same.
- Three differences found this way were fixed: a missing space between a figure and its source under "Worked out
  from" on a review item; the analyst grid's cells 8px too tall (two height classes where the Next app merges them);
  12px missing under a drafted piece's source line (the Next app keeps an empty, hidden warnings wrapper there).
- Focus rings: the shots with focus on the top bar's Home, a button-styled link, a text field and the resolution
  control differ by no more than the page they are on does.
- **Contrast:** every colour token resolves to the same value in both apps in both themes (72 values), so every
  pair's contrast is the same. 29 text and edge pairs were computed per theme and all pass (text at least 4.5:1,
  control edges and focus rings at least 3:1; the lowest are the control edge on paper, 3.25 light, and on card,
  3.20 dark). The list of 29 pairs from the earlier theme work is not in the repository, so the 29 in
  the comparison script were rebuilt from the tokens the app uses and may not be the identical list.

**Differences between the two apps found by T17 to T27:** none in behaviour. One in markup only: the locked
review's "Decision recorded on …" line has a leading space in the Vue app's text node, which does not show.

**Known gaps (not fixed):**

1. **Animation is simpler.** No `motion` library. Screens, notices, the result panel, step lines and the landing
   page's blocks fade and rise with CSS at the same durations; a review-item group opens and closes with a CSS height
   animation. Not ported: the resolution control's fill sliding between options (it switches at once), the cross-fade
   of the resolution chip, of the scorecard's sub-line and of the status bar's message when they change, and the exit
   animations of the error notices. Reduced motion is honoured by the same CSS rule as before.
2. **Font loading.** The two faces come from `@fontsource-variable` packages; `next/font` also adjusts the fallback
   font's metrics to avoid a shift while the web font loads, which this does not. Text can shift slightly on a cold
   load.
3. **The Unreachable screen names `VITE_API_TARGET`** where the Next app named its own build-time setting, and the
   "could not reach" message names the page's own origin (the proxy), not port 8000. By design (N6).
4. **No page without scripts.** The Next app serves rendered HTML; this is a single-page app and shows nothing until
   its script runs. The landing page's no-script rule has no counterpart.
5. **Unknown addresses** show a small "Page not found" page in the app's own frame; the Next app shows Next's 404.
6. **Reached only with help from the test backend.** The weekly Digital Payments draft and every Markets Review
   section run on the test suite's fixed rows and captured sources, and Fetch from CBK is answered from a saved
   bulletin (`e2e/serve_e2e.py`), so T22, T25 and T17 show what the screens do with real pipeline output, not that
   Yahoo, CBK, KNBS or afx answer. A real Word export is still stood in for in T14: the six weekly sections cannot all
   be approved on the test instance, because the weekly Real Estate draft is the one made to fail and the Focus piece
   was not drafted and approved there. A dev-mode Executive Summary (the red "Dev-mode draft" line in the panel) and
   a companion report are not exercised.
7. **Docker.** At the time of the comparison the Vue app was not in Docker. Since the cut-over the compose files
   build and serve it (`Dockerfile`).
8. **Only Chromium was used**, for the suite and the screenshots.
