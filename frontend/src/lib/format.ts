import type { ItemKind, Resolution, Status } from "./types";

export const STATUS_ORDER: Status[] = ["flagged", "not_auto_verified", "clean"];

export const STATUS_META: Record<Status, { label: string; glyph: string; title: string; hint: string }> = {
  flagged: {
    label: "Flagged",
    glyph: "!",
    title: "Flagged by the checker",
    hint: "The checker found a mismatch or a missing figure",
  },
  not_auto_verified: {
    label: "Not auto-verified",
    glyph: "?",
    title: "Not automatically verified",
    hint: "Nothing wrong found, but check it against its source by hand",
  },
  clean: {
    label: "Clean",
    glyph: "✓",
    title: "Clean",
    hint: "Checked against its source, no flag",
  },
};

export const KIND_LABELS: Record<ItemKind, string> = {
  table_row: "Table row",
  outlook_stat: "Outlook stat",
  highlight_claim: "Highlight claim",
  claim: "Drafted claim",
  unavailable_part: "Missing part",
  supplied_text: "Your text",
};

/** "Quarterly Markets Review, Q3'2026"; the bare type name for an unlabelled weekly report. */
export function reportName(title: string, period: string): string {
  return period ? `${title}, ${period}` : title;
}

export const SCOPE_LABELS: Record<string, string> = {
  investor_relations: "Investor relations site",
  web_fallback: "Web fallback",
  preferred_sources: "Preferred sources",
};

export const RESOLUTION_LABELS: Record<"none" | "accept" | "fix_needed", string> = {
  none: "Unresolved",
  accept: "Accept",
  fix_needed: "Fix needed",
};

export const RESOLUTION_CHIPS: Record<"none" | "accept" | "fix_needed", string> = {
  none: "Unresolved",
  accept: "Accepted",
  fix_needed: "Fix needed",
};

export const resolutionKey = (r: Resolution): "none" | "accept" | "fix_needed" => r ?? "none";

export const TABLE_COLUMNS: { key: string; label: string; numeric: boolean }[] = [
  { key: "company", label: "Company", numeric: false },
  { key: "ticker", label: "Ticker", numeric: false },
  { key: "current_price", label: "Price", numeric: true },
  { key: "prior_close", label: "Price 7 days ago", numeric: true },
  { key: "ytd_open", label: "Year Open", numeric: true },
  { key: "wow_pct", label: "w/w %", numeric: true },
  { key: "ytd_pct", label: "YTD %", numeric: true },
  { key: "forward_pe", label: "Forward P/E", numeric: true },
];

const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const TIME_FMT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC",
});

/** "2026-09-24" -> "24 Sep 2026" (the date is a calendar date, so it is read as UTC and never shifted). */
export function friendlyDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso : DATE_FMT.format(d);
}

/** "2026-10-01T13:24:13+00:00" -> "1 Oct 2026, 13:24 UTC"; anything unparseable is shown as stored. */
export function friendlyTime(stamp: string): string {
  const d = new Date(stamp);
  return Number.isNaN(d.getTime()) ? stamp : `${TIME_FMT.format(d).replace(" at ", ", ")} UTC`;
}

export function weekRange(start: string, end: string): string {
  return `${friendlyDate(start)} to ${friendlyDate(end)}`;
}

/** How a Python value reads in a comparison cell: strings quoted, null as None. */
export function pyRepr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (typeof value === "string") return `'${value}'`;
  return String(value);
}

export function elapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
