# Cytonn Weekly Draft Generator

AI tool that drafts the first version of the weekly Cytonn Weekly report by pulling data from spreadsheets, dashboards, past reports, and websites, mapping it into the report's existing format. Produces a ready-to-review draft instead of a blank page. Intern capstone project (Clive Mutende, Vunoh Global AI Intern Program), Option C ("full capstone") scope.

**Status as of 2026-09-28:** Proposal presented to Cytonn; verbal go-ahead to start build, official written approval still outstanding. Awaiting the three production workbooks (Equities, Fixed Income, Digital Payments) and recent report files from the team, expected this week. Build sequencing: get everything that doesn't need the workbooks working first (see Backlog below), wire in workbook fallback/cross-check once the data lands.

## Non-negotiable rules

- **Nothing in any output is invented or recalled from memory.** Every figure and claim traces to a specific source (a cited online source or the workbook).
- **Checking is exact-match after normalization, not a tolerance band.** No percentage/margin tolerance for a real error, ever. But before comparing, normalize the source value to the draft's display precision and units (round, convert, strip formatting) — this is a defined, mechanical transformation, not a fuzzy allowance. A drafted figure must equal the normalized source figure exactly.
- **A mismatch and a source disagreement are different flags.** If the draft doesn't equal its own normalized source, that's a mismatch/error flag. If two independent legitimate sources report the same underlying figure with a genuinely different derived number (e.g. two different NPL ratios off the same loan-book figure, different methodology), that's a separate **"sources disagree"** flag — it tells the coordinator a human call is needed on which source to use, it does not imply the draft is wrong.
- **The checking layer only verifies figures that trace to a source, never analysis or opinion.** A sentence like "profit rose sharply due to strong loan growth" splits into a checkable figure (the profit number) and an uncheckable interpretive claim (the "due to" framing). Check the figure; leave the interpretive language alone rather than silently marking it as verified.
- **The tool never approves anything.** A single coordinator reviews all five sections for accuracy before anything moves forward. Edwin and Liz (CEO and co) are insight recipients, not approvers — they get a Word doc summary of the coordinator-checked values *before* publish, for their own awareness, not to sign off.
- **Publishing is SSO-driven browser automation, not a direct API/DB write.** No API or database access has been confirmed or granted by Cytonn's team (CT) — the tool drives the existing admin CMS through the same SSO-authenticated session a person would use. Cytonn's backend (PHP/Laravel/nginx) is irrelevant to this — browser automation works at the DOM level regardless of backend language.

## Architecture

Two layers, per department (Equities, Fixed Income, Digital Payments, Real Estate, Focus):

1. **Drafting layer** — sources primarily online per department (see Sources below), workbook as fallback when an online source is missing/unclear. Access and settings are **section-based**, not person-based (analysts rotate sections weekly).
2. **Checking layer** — before a coordinator ever sees a draft, checks every figure against the exact (normalized) source it was drafted from and flags mismatches; see the normalization, sources-disagree, and figure-vs-analysis rules above. While the workbook is in the loop, it also serves as an independent second data point beyond match-to-source. **The workbook's role here is explicitly temporary** — phases out once online sourcing is trusted enough to stand alone. The team keeps maintaining the workbooks regardless (their own yearly rollups), so the data stays available as long as the tool needs it.

**Focus of the Week is the exception**: no fixed topic or source. The tool suggests candidate topics from historical reports; the analyst picks from the suggestions (tool doesn't choose unilaterally). Source is either analyst-supplied or tool-found, depending on that section's permission setting — either way it's surfaced to the reviewer, never guessed at silently. This is the least-tested part of the drafting layer.

**Process flow:** Suggest (Focus only) → Select → Draft (all 5 sections) → Check (exact match) → Coordinator review (single accuracy pass, all 5 sections) → Word doc summary to Edwin/Liz (insight only, before publish) → Publish (direct push into Cytonn Report admin CMS) → Distribute (CIM pages, Edwin's socials, Capital Group).

**Trigger:** automatic on the existing Friday cadence. On-demand ad-hoc ask is a later addition, not needed for the first working version.

## Sources (per department)

- **Equities / Fixed Income:** CBK (rates page, no public API — scrape), NSE (T-bill/T-bond results as per-auction PDFs, no simple API), World Bank (real public API, `?format=json`), NASI index (free public quote pages — NSE's own site, Investing.com; no paid Bloomberg Terminal needed).
- **Digital Payments:** KCB daily email (not public — needs an inbox/forwarding rule; figures split between body text and a PDF attachment).
- **Real Estate:** REIT figures from the NSE's Unquoted Securities Platform ("Ibuka"), published as a weekly PDF at a predictable filename pattern (`nse.co.ke/wp-content/uploads/Unquoted-Securities-Platform-Ibuka-Weekly-Summary_DD-MM-YYYY.pdf`) — no listing page, construct the filename from the date. Newspaper coverage: Business Daily Africa is mostly free; Daily Nation and The Standard are paywalled (paid access requested separately).
- **Focus:** historical Cytonn Weekly reports (topic suggestion), source per analyst/tool-permission as above.
- **All departments, fallback only:** the three production workbooks (Equities, Fixed Income, Digital Payments — long-running, updated weekly by the team regardless of this tool).

**Known parsing risk:** source formats drift (this is the proposal's central named risk, and Cytonn's own publishing team already hits the same problem extracting the finished PDF into their CMS). PDFs (NSE T-bills, Ibuka) need real parsing, not just a page read.

## Tech stack (decided 2026-09-28)

Python, end to end:

- Excel: `openpyxl` / `pandas`
- PDFs: `pdfplumber` (`camelot` for tricky tables — NSE T-bills, Ibuka)
- Web/API sourcing: `requests` + `BeautifulSoup` for static pages; plain `requests` for World Bank's JSON API
- CMS publish automation: **Playwright** (Python) — logs in via the existing SSO session, drives the admin CMS UI like a person would
- LLM calls (drafting, Focus topic suggestion, checking-layer flags): Anthropic Python SDK
- Word doc output (Edwin/Liz summary): `python-docx`
- Scheduler: `APScheduler` or cron, for the Friday cadence
- Internal UI (coordinator review, analyst topic pick): **Streamlit** — fastest path to a working review screen for a single-intern ~5-week build; no public-facing UI requirement, so a heavier API+frontend split isn't needed
- Storage: **SQLite** — permissions config, draft state, historical-report index, run history. No real concurrency at this scale (weekly cadence, one coordinator)
- Hosting: Cytonn's own servers, no separate hosting cost

## Backlog (current, front-loaded to what doesn't need the workbooks)

1. Initialize Python repo (Playwright, python-docx, openpyxl/pandas, pdfplumber, Streamlit, SQLite)
2. Set up section config (5 departments) + permission flags per section
3. Build CBK rates fetcher
4. Build NSE T-bill/T-bond fetcher (PDF parsing, per-auction)
5. Build World Bank data fetcher (public API)
6. Build NASI index fetcher (public quote page)
7. Build Ibuka/REIT weekly summary fetcher (predictable filename pattern PDF)
8. Unit tests for the five public-source fetchers (depends on: 3-7)
9. Design checking-layer comparison logic: normalization (precision/units), the mismatch-vs-sources-disagree flag split, and the figure-vs-analysis scope boundary
10. Build checking-layer module against sample figures, covering all three cases above (depends on: 9)
11. Draft Focus topic-suggestion logic spec
12. Scaffold historical-report ingestion for Focus topic suggestion (depends on: 11)
13. Scaffold admin CMS publish automation script (Playwright, SSO-authenticated, no live test yet)
14. Draft coordinator-review output format (single accuracy pass, all 5 sections)
15. Draft Edwin/Liz Word-doc-summary generator (python-docx, before-publish, insight-only)
16. Wire workbook fallback + cross-check into checking-layer module (depends on: 10, workbook data arriving)
17. End-to-end test, one department: draft → check → coordinator review → summary → CMS publish (depends on: 13, 14, 15, 16)

## Open items

- Two data-access requests still open: Digital Payments' KCB email access, paid Daily Nation/Standard newspaper access. Workbooks and recent report files already requested, in motion.
- Whether Cytonn (CT) would ever open real API/database access, beyond the SSO-driven UI automation — genuinely unasked, not needed for the current plan.
- Official written approval of the Inception Report is still outstanding despite the verbal go-ahead to start building.

---
*This file is the current-state reference for coding. The fuller decision history — why each of these calls was made, direct quotes, dates — lives in the "Cytonn Weekly: AI-Assisted Report Generation" Claude Project (`claude/project-status.md`), a separate surface Claude Code can't read directly. Update this file as decisions change; it won't stay in sync automatically.*