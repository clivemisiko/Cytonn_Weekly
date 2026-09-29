# Cytonn Weekly Draft Generator

AI tool that drafts the first version of the weekly Cytonn Weekly report by pulling data from spreadsheets, dashboards, past reports, and websites, mapping it into the report's existing format. Produces a ready-to-review draft instead of a blank page. Intern capstone project (Clive Mutende, Vunoh Global AI Intern Program), Option C ("full capstone") scope.

**Status as of 2026-09-29:** Proposal presented to Cytonn; verbal go-ahead to start build, official written approval still outstanding. **Pilot section for the current ~4-5 week build window: Digital Payments** — the one section committed to being built and proven fully end to end (drafting, checking, coordinator review, Word doc summary, publish, distribute) before this window closes. The other four sections (Equities, Fixed Income, Real Estate, Focus) are documented as roadmap, not built now. Digital Payments needs no workbook at all: its only source is Yahoo Finance, which also supplies the historical prices (week-ago, year-open) its weekly comparison table needs — see Sources below.

## Non-negotiable rules

- **Nothing in any output is invented or recalled from memory.** Every figure and claim traces to a specific source (a cited online source or the workbook).
- **Checking is exact-match after normalization, not a tolerance band.** No percentage/margin tolerance for a real error, ever. But before comparing, normalize the source value to the draft's display precision and units (round, convert, strip formatting) — this is a defined, mechanical transformation, not a fuzzy allowance. A drafted figure must equal the normalized source figure exactly.
- **A mismatch and a source disagreement are different flags.** If the draft doesn't equal its own normalized source, that's a mismatch/error flag. If two independent legitimate sources report the same underlying figure with a genuinely different derived number (e.g. two different NPL ratios off the same loan-book figure, different methodology), that's a separate **"sources disagree"** flag — it tells the coordinator a human call is needed on which source to use, it does not imply the draft is wrong.
- **The checking layer only verifies figures that trace to a source, never analysis or opinion.** A sentence like "profit rose sharply due to strong loan growth" splits into a checkable figure (the profit number) and an uncheckable interpretive claim (the "due to" framing). Check the figure; leave the interpretive language alone rather than silently marking it as verified.
- **There are no "departments," only report sections** (Equities, Fixed Income, Digital Payments, Real Estate, Focus). Analysts rotate across sections weekly; permissions and config are section-based, not person-based.
- **The tool never approves anything.** A single coordinator reviews all five sections for accuracy before anything moves forward. Edwin and Liz (CEO and co) are insight recipients, not approvers — they get a Word doc summary of the coordinator-checked values *before* publish, for their own awareness, not to sign off.
- **Publishing is SSO-driven browser automation, not a direct API/DB write.** No API or database access has been confirmed or granted by Cytonn's team (CT) — the tool drives the existing admin CMS through the same SSO-authenticated session a person would use. Cytonn's backend (PHP/Laravel/nginx) is irrelevant to this — browser automation works at the DOM level regardless of backend language.

## Architecture

Two layers, per section (Equities, Fixed Income, Digital Payments, Real Estate, Focus):

1. **Drafting layer** — sources primarily online per section (see Sources below), workbook as fallback when an online source is missing/unclear. Access and settings are **section-based**, not person-based (analysts rotate sections weekly).
2. **Checking layer** — before a coordinator ever sees a draft, checks every figure against the exact (normalized) source it was drafted from and flags mismatches; see the normalization, sources-disagree, and figure-vs-analysis rules above. While the workbook is in the loop, it also serves as an independent second data point beyond match-to-source. **The workbook's role here is explicitly temporary** — phases out once online sourcing is trusted enough to stand alone. The team keeps maintaining the workbooks regardless (their own yearly rollups), so the data stays available as long as the tool needs it.

**Focus of the Week is the exception**: no fixed topic or source. The tool suggests candidate topics from historical reports; the analyst picks from the suggestions (tool doesn't choose unilaterally). Source is either analyst-supplied or tool-found, depending on that section's permission setting — either way it's surfaced to the reviewer, never guessed at silently. This is the least-tested part of the drafting layer.

**Process flow:** Suggest (Focus only) → Select → Draft (all 5 sections) → Check (exact match) → Coordinator review (single accuracy pass, all 5 sections) → Word doc summary to Edwin/Liz (insight only, before publish) → Publish (direct push into Cytonn Report admin CMS) → Distribute (CIM pages, Edwin's socials, Capital Group).

**Trigger:** automatic on the existing Friday cadence. On-demand ad-hoc ask is a later addition, not needed for the first working version.

## Sources (per section)

- **Equities:** CBK (rates page, no public API — scrape), NSE (T-bill/T-bond results as per-auction PDFs, no simple API), World Bank (real public API, `?format=json`), NASI index (free public quote pages — NSE's own site, Investing.com; no paid Bloomberg Terminal needed), **and the KCB daily email** (not public — needs an inbox/forwarding rule; figures split between body text and a PDF attachment).
- **Fixed Income:** CBK, NSE (T-bill/T-bond per-auction PDFs), World Bank, NASI — same public sources as Equities, no email dependency.
- **Digital Payments** has two distinct parts, confirmed against a real Cytonn Weekly report (pages 16-18):
  - **The stock table** ("Digital Payments NYSE and LSE Stock Performance"): Yahoo Finance (free, no access request needed) — the only source this needs. Covers **7 companies: American Express, Visa, Mastercard, Circle, Block, PayPal, Global Payments** — all NYSE/NASDAQ, no LSE names despite the table's title. **Wise Plc is not in it**: the report's intro sentence names Wise (and skips Circle and Global Payments, which *are* in the table), but that sentence is stale boilerplate, not a reliable company list — go by the table's actual rows. Needs, per company: current price, price 7 days ago, and this year's open price, to compute w/w % change and YTD % change — all three are ordinary historical prices Yahoo Finance holds for any past date, no workbook or stored run history needed. The table's one non-weekly input, Forward P/E, is off FY'2025 audited financials — an annual figure worth sourcing/caching separately, not re-pulled every run. **Confirmed working tickers:** AXP, V, MA, CRCL, XYZ (not the old SQ symbol — Block rebranded), PYPL, GPN.
  - **"Weekly Highlights"** (4 narrative write-ups on real payments-industry news — e.g. a Visa research release, a Mastercard partnership announcement — confirmed as exactly 4 across two real issues, not a range): sourced via Claude's native web search tool (see Tech stack), scoped strictly to the 7 confirmed companies above, no broader industry news. Each highlight's factual claims carry a citation the checking layer verifies against; the closing bold-italic outlook paragraph is interpretive synthesis, never checked, per the figure-vs-analysis rule above. This is real added scope beyond the table, decided 2026-09-29 so the pilot's "fully automated drafting" claim covers the whole section, not just the checkable numbers.
- **Real Estate:** REIT figures from the NSE's Unquoted Securities Platform ("Ibuka"), published as a weekly PDF at a predictable filename pattern (`nse.co.ke/wp-content/uploads/Unquoted-Securities-Platform-Ibuka-Weekly-Summary_DD-MM-YYYY.pdf`) — no listing page, construct the filename from the date. Newspaper coverage: Business Daily Africa is mostly free; Daily Nation and The Standard are paywalled (paid access requested separately).
- **Focus:** historical Cytonn Weekly reports (topic suggestion), source per analyst/tool-permission as above.
- **All sections, fallback only:** the three production workbooks (Equities, Fixed Income, Digital Payments — long-running, updated weekly by the team regardless of this tool).

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
- Web search (Digital Payments' narrative highlights, and any future section's open-ended research): **Anthropic Messages API's native web search tool** (`web_search_20250305` or newer) — server-side, no separate search API/account needed, same SDK and billing already in use. Returns mandatory citations (URL, title, cited text) per result, which is what the checking layer uses to verify narrative claims against their source. ~$10/1,000 searches + token cost — negligible at this project's scale.

## Backlog (current, scoped to the Digital Payments pilot — see Status above)

1. ~~Initialize Python repo (Playwright, python-docx, openpyxl/pandas, pdfplumber, Streamlit, SQLite)~~ — **done**, two commits (`1f92db9`, `1828d0e`)
2. ~~Set up section config (5 sections) + permission flags per section~~ — **done** (`sections.py`, seeded, 19 tests passing)
3. ~~Build Digital Payments' Yahoo Finance fetcher~~ — **done**, `digital_payments.py`, confirmed against the 7 real tickers (AXP, V, MA, CRCL, XYZ, PYPL, GPN), Wise Plc removed. Not yet committed — awaiting manual commit (Claude Code no longer commits/pushes, that's manual now).
4. ~~Unit tests for the Yahoo Finance fetcher~~ — **done**, 25 tests passing, updated for the 7-company list
5. Build the Digital Payments "Weekly Highlights" drafter — **next**: Claude's native web search tool finds recent payments-industry news about the 7 confirmed companies only (Amex, Visa, Mastercard, Circle, Block, PayPal, Global Payments — no broader industry news), picks exactly 4 stories genuinely from that week (confirmed against two real issues, not a 4-5 range), and drafts each as a headline + ~100-180 word paragraph opening "During the week, [Company]...", matching the report's real format (numbered I-IV, stock table as item V — already built in task 3). Every factual claim keeps its source citation (URL) recorded for the checking layer, and the source is also embedded as an inline hyperlink on natural anchor text within the paragraph, matching the report's own style — not a footnote list. Also drafts the closing bold-italic outlook paragraph (~80-120 words) synthesizing the week's highlights and the table's average P/E/trend — this is interpretive synthesis, not a new sourced claim, so it carries no citation and the checking layer never verifies it (per the figure-vs-analysis rule).
8. Draft coordinator-review output format (single accuracy pass, scoped to Digital Payments — table and highlights together)
9. Build the coordinator-review screen (Streamlit), scoped to Digital Payments (depends on: 8)
10. Build the Edwin/Liz Word-doc-summary generator (python-docx, before-publish, insight-only), scoped to Digital Payments
11. Scaffold and build admin CMS publish automation (Playwright, SSO-authenticated), scoped to Digital Payments' section of the CMS
12. End-to-end test, Digital Payments: draft (table + highlights) → check → coordinator review → summary → CMS publish → distribute (depends on: 7, 9, 10, 11)

**Documented as roadmap beyond this window, not built now:**
- Extending drafting and checking to the remaining four sections (Equities, Fixed Income, Real Estate, Focus) — includes the CBK, NSE T-bill/T-bond, World Bank, NASI, and Ibuka/REIT fetchers, the Focus topic-suggestion logic, and historical-report ingestion
- Workbook fallback/cross-check wiring — not needed for Digital Payments; may matter once other sections come into scope
- The on-demand (ask-anytime) trigger, beyond the automatic Friday-cadence run
- Full hardening against source-format drift across every section's sources

## Open items

- Two data-access requests still open, neither blocking the Digital Payments pilot: an inbox/forwarding rule for Equities' KCB daily email, and paid access to Daily Nation/The Standard for Real Estate's newspaper coverage.
- Whether Cytonn (CT) would ever open real API/database access, beyond the SSO-driven UI automation — genuinely unasked, not needed for the current plan.
- Official written approval of the Inception Report is still outstanding despite the verbal go-ahead to start building.

---
*This file is the current-state reference for coding. The fuller decision history — why each of these calls was made, direct quotes, dates — lives in the "Cytonn Weekly: AI-Assisted Report Generation" Claude Project (`claude/project-status.md`), a separate surface Claude Code can't read directly. Update this file as decisions change; it won't stay in sync automatically.*