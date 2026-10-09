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
  | "carried_text";

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

export type Block = TableBlock | NarrativeBlock | UnavailableBlock | SuppliedBlock | ComputedBlock | CarriedBlock;

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

export interface StatusCounts {
  total: number;
  unresolved: number;
  fix_needed: number;
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
