// The JSON the FastAPI layer serves (api/serialize.py). The web app derives nothing the API already knows.

export type Status = "flagged" | "not_auto_verified" | "clean";
export type Resolution = "accept" | "fix_needed" | null;
export type ItemKind =
  | "table_row"
  | "outlook_stat"
  | "highlight_claim"
  | "claim"
  | "unavailable_part"
  | "supplied_text"
  | "computed_figure"
  | "carried_text"
  | "chart";

// ---- Report types (report_types.py): which report a review belongs to ----

export type ReportType = "weekly" | "quarterly" | "half_year" | "annual" | "companion";

/** What the coordinator picked: a report type, its period label, and (companion reports only) which report. */
export interface ReportChoice {
  type: ReportType;
  period: string;
  kind: string | null;
}

export interface ReportTypeInfo {
  slug: ReportType;
  title: string;
  /** The real issue this type was verified against. */
  published_as: string;
  period_hint: string;
  period_required: boolean;
  /** The most recent period of this type that has ended (the API's suggestion; "" for weekly labels). */
  suggested_period: string;
}

export interface CompanionKind {
  slug: string;
  title: string;
  issue: string;
  published: string;
}
export type Decision = "approved" | "rejected";

export interface Flag {
  kind: string;
  scope: string;
  subject: string;
  field: string | null;
  message: string;
  drafted: unknown;
  expected: string | null;
  source_value: unknown;
  decimals: number | null;
  sources: { source: string; value: unknown; normalized: unknown }[];
}

/** One input of a computed figure: its value, where it was read, and (if any) a second reading of it. */
export interface FigureInput {
  value: unknown;
  origin: "source" | "analyst_input" | "ocr";
  source: string;
  second?: { value: unknown; source: string; origin?: string } | null;
}

export interface ClaimContext {
  text?: string;
  url?: string;
  title?: string;
  cited_text?: string;
  /** Computed figures only: what the figure was worked out from. */
  inputs?: Record<string, FigureInput>;
  note?: string;
}

export interface ReviewItem {
  index: number;
  kind: ItemKind;
  ref: string;
  status: Status;
  /** Flag objects when flagged, the fixed note when not auto-verified, null when clean. */
  detail: Flag[] | string | null;
  resolution: Resolution;
  resolution_note: string | null;
  context: ClaimContext;
}

export interface Claim {
  text: string;
  url: string;
  title: string;
  cited_text: string;
}

export interface HighlightItem {
  numeral: string;
  kind: "highlight";
  headline: string;
  headline_md: string;
  body_md: string;
  claims: Claim[];
  warnings: string[];
  company: string;
  search_scope: "investor_relations" | "web_fallback" | string;
  ir_domain: string | null;
  drafted_by: string;
}

export interface TableRow {
  company: string;
  ticker: string;
  current_price: string;
  prior_close: string;
  ytd_open: string;
  wow_pct: string;
  ytd_pct: string;
  forward_pe: string;
  flagged: boolean;
  error: string | null;
}

export interface StockTableItem {
  numeral: string;
  kind: "stock_table";
  title: string;
  rows: TableRow[];
}

export interface Outlook {
  text_md: string;
  stats: { key: string; value: string }[];
  warnings: string[];
  drafted_by: string | null;
}

/** Digital Payments' own section shape (highlights, stock table, outlook). */
export interface Section {
  week_start: string;
  week_end: string;
  highlights_found: number;
  highlights_expected: number;
  shortfall: number;
  warnings: string[];
  items: (HighlightItem | StockTableItem)[];
  outlook: Outlook;
}

// ---- Every other section: generic blocks, tables already display-formatted by the API ----

export interface TableColumn {
  key: string;
  label: string;
  numeric: boolean;
}

export interface TableBlock {
  numeral: string;
  kind: "table";
  id: string;
  title: string;
  columns: TableColumn[];
  key_field: string;
  /** `typed`: the row's figures match their source, but the source is a cell an analyst typed. */
  rows: (Record<string, string> & { flagged: boolean; error: string | null; typed?: boolean })[];
  source: { name: string; url: string | null; as_of: string | null };
  footnotes?: string[] | null;
  notes?: string[] | null;
}

/** One figure of a computed paragraph, with what it was made from. */
export interface ComputedFigure {
  key: string;
  label: string;
  display: string;
  note?: string;
  inputs: Record<string, FigureInput>;
}

/** A paragraph the tool worked out from published figures; every figure in it is a review item. */
export interface ComputedBlock {
  numeral: string;
  kind: "computed";
  id: string;
  title: string;
  body_md: string;
  figures: ComputedFigure[];
  sources: { name: string; url?: string | null }[];
  notes: string[];
}

/** Text copied from the previous issue: always flagged "carried forward, edit before approving". */
export interface CarriedBlock {
  numeral: string;
  kind: "carried";
  id: string;
  title: string;
  body_md: string;
  carried_from: { issue_id: number | null; url: string | null; published: string | null };
}

export interface NarrativeBlock {
  numeral: string;
  kind: "narrative";
  id: string;
  topic: string;
  headline: string;
  body_md: string;
  claims: Claim[];
  warnings: string[];
  search_scope: string | null;
  preferred_domains: string[];
  drafted_by: string;
}

export interface UnavailableBlock {
  numeral: string;
  kind: "unavailable";
  id: string;
  title: string;
  reason: string;
  unblock: string;
}

/** Text the coordinator supplied (Company Updates): carried verbatim, never drafted or checked. */
export interface SuppliedBlock {
  numeral: string;
  kind: "supplied";
  id: string;
  title: string;
  body_md: string;
  supplied_by: string;
  /** Shown beside the text as context only (the NSE curve beside the analysts' bidding range). */
  context?: string | null;
}

export interface ChartDefect {
  kind: string;
  message: string;
  cells: string[];
  /** A blocking defect is why the chart was not drawn. */
  blocking: boolean;
}

/**
 * A chart the tool draws from the analyst workbook (charts/block.py). Metadata only: the picture and the series come from their
 * own routes. `no_workbook` means no workbook was uploaded, so nothing was read: information, with no review item.
 * `use_team_chart` is true while the coordinator has set the tool's chart aside for the team's own.
 */
export interface ChartBlock {
  numeral: string;
  kind: "chart";
  id: string;
  chart_id: string;
  title: string;
  caption: string;
  status: "drawn" | "not_drawn" | "no_workbook";
  unit: "multiple" | "pct";
  use_team_chart: boolean;
  reason: string | null;
  unblock: string | null;
  alt: string | null;
  source: { workbook: string; sheet: string; provenance: string; cells: string | null } | null;
  points: number;
  window: { years: number; first: string; last: string; points: number } | null;
  newest_date: string | null;
  last_value: { display: string; value: string; cell: string } | null;
  average: { display: string; value: string; count: number; first: string; last: string; cells: string; from: string; note: string | null } | null;
  stated: { cell: string; value: string | null; formula_range: string | null } | null;
  png_sha256: string | null;
  defects: ChartDefect[];
}

/** The stored series a chart was drawn from: [date, value, cell, display] per point, oldest first. */
export interface ChartSeriesFile {
  chart_id: string;
  week_ending: string;
  workbook: string;
  sheet: string;
  unit: string;
  points: [string, string, string, string][];
}

export type Block = TableBlock | NarrativeBlock | UnavailableBlock | SuppliedBlock | ComputedBlock | CarriedBlock | ChartBlock;

export interface NotCovered {
  section: string;
  title: string;
  run_id: number;
  tables: string[];
  unavailable: string[];
  further_pieces: string[];
  /** Pieces of the approved section drafted by the local (dev-only) model, carried into the summary or not. */
  dev_pieces: { piece: string; drafted_by: string }[];
}

export interface BlocksSection {
  week_start: string;
  week_end: string;
  /** The weekly sections worked out from the week's inputs: the Friday the week ends on. */
  week_ending?: string | null;
  /** Markets Reviews only: the period the section covers. */
  period_start?: string | null;
  period_end?: string | null;
  topic: string | null;
  pieces_found: number;
  pieces_expected: number;
  shortfall: number;
  warnings: string[];
  /** Markets Reviews only: the real issue's chart titles, which the tool does not draw. */
  chart_notes?: string[];
  chart_reference?: string | null;
  /** Executive Summary only: how it is composed, and per included section what the summary leaves out. */
  summary_note?: string | null;
  not_covered?: NotCovered[];
  blocks: Block[];
}

export const isBlocksSection = (s: Section | BlocksSection): s is BlocksSection => "blocks" in s;

/** One stored weekly input: what was received and the date the API read from the file itself. */
export interface InputFile {
  stored_name: string;
  read_date: string | null;
  /** Whether the file's own date is this week's. */
  matches: boolean;
  note: string;
  size: number;
  original_name: string;
  received_at: string;
  fetched_from: string | null;
}

export interface InputSlot {
  slug: string;
  title: string;
  kind: "pdf" | "xlsx";
  optional: boolean;
  /** One file per trading day (the KCB IB daily reports). */
  per_day: boolean;
  /** The API can fetch it itself (the CBK Weekly Bulletin). */
  fetchable: boolean;
  help: string;
  received: boolean;
  complete: boolean;
  file?: InputFile | null;
  days?: { date: string; weekday: string; received: boolean; file: InputFile | null }[];
}

/** Whether the week's report can be exported, with each weekly section's state. */
export interface ExportStatus {
  period: string;
  ready: boolean;
  sections: { slug: string; title: string; state: "approved" | "in_review" | "rejected" | "not_drafted"; run_id: number | null }[];
  is_dev_draft: boolean;
  dev_sections: string[];
  dev_mode_label: string | null;
  can_send: boolean;
  file_name: string;
}

/** "This week's inputs" for one report week. */
export interface WeeklyInputs {
  week_ending: string;
  monday: string;
  previous_friday: string;
  slots: InputSlot[];
  notes: { bidding_range?: string; previous_issue?: string };
  max_bytes: number;
}

/** Where a value came from while it is still what was carried from last week's form, or what was suggested. */
export interface AnalystCarried {
  /** The week it was carried from (ISO date), or "suggested" for a worked-out running total. */
  from: string;
  /** A suggestion's working, in the API's words. */
  note: string;
  /** The whole item is as carried; false when a grid was edited and only `cells` still are. */
  whole: boolean;
  /** Per row name, the columns still holding the carried value. */
  cells: Record<string, string[]>;
}

/** One typed field of the "Weekly analyst inputs" form, with what an uploaded workbook holds for it. */
export interface AnalystField {
  type: "field";
  key: string;
  label: string;
  kind: "number" | "date" | "names";
  unit: string;
  min: number | null;
  max: number | null;
  /** Where the analysts read it ("Business Daily", "Bloomberg NASI P/E"). */
  source: string;
  help: string;
  /** The part of the section that prints it. */
  used_in: string;
  /** As typed (a list for the large-cap names); null when nothing is typed. */
  value: string | string[] | null;
  workbook: { value: string | string[]; ref: string } | null;
  /** Why the uploaded workbook could not supply it, if it could not. */
  workbook_note: string | null;
  /** Typed values that differ from the uploaded workbook's, in the API's words. */
  differences: string[];
  carried: AnalystCarried | null;
  /** Carried or suggested and not confirmed yet: no draft reads it, and the draft button waits. */
  needs_confirmation: boolean;
  /** A running total the API can work a suggestion out for. */
  suggestable: boolean;
  /** What is used when nothing is typed and no workbook holds it (the fiscal year's start: 1 July). */
  default: string | null;
}

export interface AnalystColumn {
  key: string;
  label: string;
  kind: "text" | "number" | "date" | "month" | "rank" | "check";
  unit: string;
  min: number | null;
  max: number | null;
  required: boolean;
}

export type AnalystRow = Record<string, string>;

/**
 * One table of the form: pasted lines (the fund table) or a grid typed cell by cell (the Universe of Coverage).
 */
export interface AnalystTable {
  type: "table";
  key: string;
  label: string;
  mode: "paste" | "grid";
  source: string;
  help: string;
  example: string;
  used_in: string;
  columns: AnalystColumn[];
  /** A grid whose rows are given (the five Eurobond issues); empty for a grid of any number of rows. */
  fixed_rows: { key: string; label: string }[];
  rows: AnalystRow[] | null;
  /** The typed rows as lines the paste box reads back. */
  text: string;
  workbook_rows: AnalystRow[] | null;
  workbook_ref: string | null;
  workbook_note: string | null;
  warnings: string[];
  differences: string[];
  carried: AnalystCarried | null;
  needs_confirmation: boolean;
  /** What a row gets without typing: this Friday's price from KCB IB, last Friday's from the stored week. */
  auto_rows: AnalystRow[] | null;
  auto_note: string;
}

export type AnalystItem = AnalystField | AnalystTable;

export interface AnalystForm {
  form: string;
  week_ending: string;
  saved_at: string | null;
  groups: { section: string; key: string; title: string; items: AnalystItem[] }[];
  /** Whether each section's workbook is among the week's uploads. */
  workbooks: Record<string, boolean>;
  /** The Friday before this week's, and whether a form is saved for it to start from. */
  previous_week: string;
  can_carry: boolean;
  /** Carried or suggested values still waiting to be confirmed, on this section's part of the form. */
  unconfirmed: { key: string; label: string }[];
}

export interface StatusCounts {
  total: number;
  unresolved: number;
  fix_needed: number;
}

/** GET /api/reviews/{run_id}/rejected-draft-notes: what was said about the rejected draft just before this one. */
export interface RejectedDraftNotes {
  run_id: number;
  decided_at: string | null;
  entries: { ref: string; resolution: Resolution; note: string | null }[];
}

export interface Review {
  section_slug: string;
  section_title: string;
  /** The report this review belongs to; with the section slug, its key. */
  report_type: ReportType;
  report_title: string;
  /** "" only for a weekly review with no label. */
  period: string;
  run_id: number;
  decision: Decision | null;
  decided_at: string | null;
  locked: boolean;
  is_approvable: boolean;
  is_dev_draft: boolean;
  dev_mode_label: string | null;
  progress: { total: number; resolved: number; unresolved: number; fix_needed: number };
  counts: Record<Status, StatusCounts>;
  section: Section | BlocksSection;
  /** The section's summary for the CMS, composed from its own lead paragraphs ("" when it has none). */
  summary?: string;
  review_items: ReviewItem[];
}

export interface AppConfig {
  provider: string;
  provider_valid: boolean;
  dev_mode: boolean;
  dev_mode_label: string;
  spends_api_budget: boolean;
  /** Why a draft cannot run with this provider (e.g. no ANTHROPIC_API_KEY), or null. The API refuses such drafts. */
  provider_problem: string | null;
}

// ---- A draft run (POST /api/runs, GET /api/runs/{id}, GET /api/runs/{id}/events) ----

export type RunEventKind =
  | "run_started"
  | "source_started"
  | "source_finished"
  | "source_failed"
  | "piece_started"
  | "piece_finished"
  | "part_skipped"
  | "check_started"
  | "check_finished"
  | "run_finished"
  | "run_failed";

/** One real step of a draft, as the pipeline reported it (common/run_events.py). */
export interface RunEvent {
  /** 1, 2, 3, ... within the run. */
  seq: number;
  kind: RunEventKind;
  label: string;
  detail: string | null;
  /** check_finished and run_finished only: review items per status. */
  counts: Record<Status, number> | null;
  /** UTC, ISO 8601. */
  at: string;
}

/** A run as the API holds it, in memory only: unknown (404) after the API restarts. */
export interface Run {
  run_id: string;
  report_type: ReportType;
  report_title: string;
  period: string;
  section: string;
  section_title: string;
  status: "running" | "finished" | "failed";
  /** The saved review, once the run has finished. */
  review_id: number | null;
  /** As the review serializer computes it; null until the review exists. */
  is_dev_draft: boolean | null;
  dev_mode_label: string | null;
  events: RunEvent[];
}

// ---- The overview (GET /api/sections) ----

export interface LatestRun {
  run_id: number;
  run_date: string;
  this_week: boolean;
  /** The run to resume: this week's for an unlabelled weekly run, always for a run labelled with a period. */
  current: boolean;
  decision: Decision | null;
  decided_at: string | null;
  progress: Review["progress"];
  counts: Record<Status, StatusCounts>;
  is_dev_draft: boolean;
  week_start: string | null;
  week_end: string | null;
  topic: string | null;
}

export interface SectionSummary {
  slug: string;
  title: string;
  available: boolean;
  needs_topic: boolean;
  /** Company Updates: the coordinator pastes the text; nothing is drafted. */
  needs_text: boolean;
  /** Executive Summary: composed only once every other section of this report and period is approved. */
  requires_approved: boolean;
  /** False when drafting calls no LLM (no API budget, no API key needed, no draft slot). */
  uses_provider: boolean;
  /** Unavailable sections only: what blocks a draft, what would unblock it, and what is already built. */
  reason: string | null;
  unblock: string | null;
  built_parts: string[];
  /** The real issue's own headings for this section, verbatim. */
  subsections: string[];
  /** The real issue's charts for this section; the tool does not draw them. */
  charts: string[];
  steps: { title: string; body: string }[];
  latest: LatestRun | null;
}

/** The draft running right now. One runs at a time across every section, and it is not saved until it finishes. */
export interface Drafting {
  slug: string;
  title: string;
  /** Which report the running draft is for; the same slug drafts in several report types. */
  report_type?: ReportType;
  period?: string;
  started_at: string;
  elapsed_seconds: number;
  /** Ran past `stale_after_seconds`: treated as stuck, and the next draft replaces it. */
  stale: boolean;
  stale_after_seconds: number;
}

export interface Overview {
  today: string;
  drafting: Drafting | null;
  /** The report these sections belong to, as the API normalized it. */
  report: {
    type: ReportType;
    title: string;
    period: string;
    kind: string | null;
    published_as: string;
    /** Weekly only: the Friday the period names ("Week ending 2026-10-02"), and the Friday to suggest. */
    week_ending?: string | null;
    suggested_week_ending?: string;
  };
  report_types: ReportTypeInfo[];
  companion_kinds: CompanionKind[];
  sections: SectionSummary[];
}

// -- Notable this week (backend/src/cytonn_weekly/notable/) ------------------------------------------------------

export type SuggestionKind = "streak" | "record" | "since" | "trailing_compare" | "threshold_cross" | "expected_range" | "pace" | "drift";
export type DismissReason = "not_relevant" | "already_covered" | "figures_look_wrong" | "other";

/** What the analyst did with a suggestion; null on the suggestion when nothing yet. */
export interface SuggestionDecision {
  decision: "selected" | "dismissed";
  /** The analyst's rewording, on a selected suggestion; the original headline is never changed. */
  edited_headline: string | null;
  dismiss_reason: DismissReason | null;
  decided_at: string;
}

/** A note to the analyst, built by code from history with the working that produced it. Never written into a draft. */
export interface Suggestion {
  id: string;
  kind: SuggestionKind;
  section: string;
  week_ending: string;
  headline: string;
  figures: { label: string; value: number; display: string; unit: string }[];
  working: { series: string; rule: string; window: string; points: { date: string; value: number; display: string }[] };
  /** `label` for a workbook-derived item reads "from the analyst workbook, not verified", for an invented one "invented demo item". */
  provenance: { kind: "published" | "approved_review" | "analyst_workbook" | "typed" | "demo"; label: string };
  /** 0 to 100. */
  rank: number;
  version: number;
  decision: SuggestionDecision | null;
}

/** GET /api/notable/{section}: the section's suggestions for the week, and how many checks could not run. */
export interface Notable {
  section: string;
  week_ending: string | null;
  suggestions: Suggestion[];
  failed_checks: number;
}
