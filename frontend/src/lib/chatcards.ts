import { isLive, providerOff } from "./drafting";
import type { AppConfig, Drafting, Review, ReviewItem, SectionSummary } from "./types";

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown) => (typeof v === "string" ? v : "");
const num = (v: unknown) => (typeof v === "number" ? v : 0);
const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? v.filter(isObject) : []);

/** "Week ending 2026-10-09" -> "2026-10-09" (the form the inputs routes take). */
export const weekOf = (period: string) => period.replace(/^Week ending /, "");

// ---- The readiness check: the saved card and the live re-run have one shape ----

export type GroupKey = "needs_analyst" | "carried_or_suggested" | "fetched" | "in_place" | "optional";

/** The five groups in the order they are shown, with what each means in words (a group is a heading, never a colour). */
export const GROUPS: { key: GroupKey; heading: string; meaning: string }[] = [
  { key: "needs_analyst", heading: "Needs you", meaning: "Nothing is in place for these yet." },
  { key: "carried_or_suggested", heading: "Carried or suggested", meaning: "Filled from last week or suggested, and not yet confirmed by you." },
  { key: "fetched", heading: "Fetched", meaning: "The tool fetched these." },
  { key: "in_place", heading: "In place", meaning: "Uploaded or typed." },
  { key: "optional", heading: "Optional", meaning: "Not required for the draft." },
];

export interface ReadinessEntry {
  kind: string;
  key: string;
  label: string;
  why: string;
}
export interface SnipCount {
  sector: string;
  uploaded: number;
  read: number;
  confirmed: number;
}
export interface SourceCount {
  total: number;
  inWeek: number;
  outsideWeek: number;
}
export interface Readiness {
  section: string;
  weekEnding: string;
  groups: Record<GroupKey, ReadinessEntry[]>;
  /** Real Estate only: the analyst's snips per sector. Counts, with no verdict. */
  snips: SnipCount[] | null;
  /** Real Estate and Focus: the saved sources. Counts, with no verdict. */
  sources: SourceCount | null;
  note: string | null;
}

/** Shown whenever counts are shown with no verdict, in the API's words when it sent them. */
export const NOT_JUDGED = "The snip and source counts are as they are: this check does not say whether they are enough.";

export function parseReadiness(data: unknown): Readiness | null {
  if (!isObject(data) || !isObject(data.groups) || typeof data.week_ending !== "string") return null;
  const groups = {} as Record<GroupKey, ReadinessEntry[]>;
  for (const { key } of GROUPS) {
    groups[key] = list(data.groups[key]).map((e) => ({ kind: text(e.kind), key: text(e.key), label: text(e.label), why: text(e.why) }));
  }
  const snips = Array.isArray(data.snips) ? list(data.snips).map((s) => ({ sector: text(s.sector), uploaded: num(s.uploaded), read: num(s.read), confirmed: num(s.confirmed) })) : null;
  const s = isObject(data.sources) ? data.sources : null;
  const sources = s ? { total: num(s.total), inWeek: num(s.in_week), outsideWeek: num(s.outside_week) } : null;
  const counted = snips !== null || sources !== null;
  return { section: text(data.section), weekEnding: data.week_ending, groups, snips, sources, note: text(data.note) || (counted ? NOT_JUDGED : null) };
}

export const snipLine = (s: SnipCount) => `${s.sector}: ${s.uploaded} uploaded, ${s.read} read, ${s.confirmed} confirmed`;
export const sourcesLine = (s: SourceCount) => `${s.total} saved, ${s.inWeek} dated inside the week, ${s.outsideWeek} outside it`;

/** The one input the tool can fetch itself; the bulletin route is the only fetch route there is. */
export const FETCHABLE = ["cbk_bulletin"];

/** Form tables the tool fetches from CBK (POST .../analyst/fetch/{key}), with the words on their buttons. */
export const FETCHABLE_ITEMS: Record<string, string> = { interbank: "Fetch interbank rates from CBK", remittances: "Fetch remittances from CBK", eurobond_yields: "Fetch Eurobond openings from CBK" };

export interface NeedsYou {
  /** Files to upload (and, for the bulletin, to fetch). */
  uploads: (ReadinessEntry & { fetchable: boolean })[];
  /** Form tables the tool can fetch, still empty (needed or optional): a button each. */
  fetch: ReadinessEntry[];
  /** Form values with nothing typed that the chat takes inline (the "Type these here" card). */
  inline: ReadinessEntry[];
  /** Form values with nothing typed that are still typed on the inputs form. */
  typed: ReadinessEntry[];
  /** Form values carried or suggested: they need confirming on the inputs form. */
  confirm: ReadinessEntry[];
}

/** What the "needs you" card offers: only what is missing or unconfirmed, split by the button each one takes. */
export function needsYou(r: Readiness): NeedsYou {
  const open = r.groups.needs_analyst;
  const fetchable = (e: ReadinessEntry) => e.kind === "table" && e.key in FETCHABLE_ITEMS;
  return {
    uploads: open.filter((e) => e.kind === "upload").map((e) => ({ ...e, fetchable: FETCHABLE.includes(e.key) })),
    fetch: [...open, ...r.groups.optional].filter(fetchable),
    inline: open.filter((e) => !fetchable(e) && isInline(e)),
    typed: open.filter((e) => e.kind !== "upload" && !fetchable(e) && !isInline(e)),
    confirm: r.groups.carried_or_suggested,
  };
}
export const hasNeeds = (n: NeedsYou) => n.uploads.length + n.fetch.length + n.inline.length + n.typed.length + n.confirm.length > 0;

/** Stay on the inputs form: the fund table and its two lines belong to the fund table card, the large-cap list is a names box. */
export const FORM_ONLY = ["mmf", "mmf_published", "mmf_source", "large_caps"];
/** A form field or table the chat can take: the field gets a box and Save, the table the form's own editor. */
export const isInline = (e: ReadinessEntry) => (e.kind === "field" || e.kind === "table") && !FORM_ONLY.includes(e.key);

/** The card's steps are the inline lines missing when it first appears; later reads never add, drop or reorder them. */
export const captureSteps = (prev: ReadinessEntry[] | null, inline: ReadinessEntry[]) => prev ?? (inline.length ? inline : null);
/** Indexes of the steps not saved yet (skipped, or not reached), in step order. */
export const unsavedSteps = (steps: ReadinessEntry[], saved: Record<string, string>) =>
  steps.flatMap((s, i) => (s.key in saved ? [] : [i]));

/** Checked before the save is sent; every other check is the API's, in its own words (a blank would clear the value). */
export const typedProblem = (text: string) => (text.trim() ? null : "Type a value before saving.");

// ---- The review summary the code saves when a draft finishes ----

export interface ReviewSnapshot {
  reviewId: number;
  isDev: boolean;
  decision: string | null;
  counts: { flagged: number; notAuto: number; clean: number };
  items: { index: number; ref: string; status: string }[];
}

export function parseReviewSnapshot(card: Record<string, unknown>): ReviewSnapshot | null {
  const data = card.data;
  if (!isObject(data) || !isObject(data.counts) || typeof card.review_id !== "number") return null;
  const c = data.counts;
  return {
    reviewId: card.review_id,
    isDev: card.is_dev_draft === true,
    decision: typeof data.decision === "string" ? data.decision : null,
    counts: { flagged: num(c.flagged), notAuto: num(c.not_auto_verified), clean: num(c.clean) },
    items: list(data.items).map((i) => ({ index: num(i.index), ref: text(i.ref), status: text(i.status) })),
  };
}

export const STATUS_WORDS: Record<string, string> = { flagged: "Flagged", not_auto_verified: "Not auto-verified", clean: "Clean" };

/** The flagged items of a live review, each with the first thing the checker said. */
export function flaggedOf(review: Review): { item: ReviewItem; why: string }[] {
  return review.review_items
    .filter((i) => i.status === "flagged")
    .map((item) => ({ item, why: (Array.isArray(item.detail) ? item.detail[0]?.message : typeof item.detail === "string" ? item.detail : "") ?? "" }));
}

// ---- The draft card: ready, running, queued, failed or not offered, and why ----

export type DraftCard =
  | { kind: "none"; why: string }
  | { kind: "ready"; again: boolean }
  | { kind: "blocked"; why: string }
  | { kind: "running" | "queued"; drafting: Drafting }
  | { kind: "failed"; why: string };

/** The topic and section titles of Focus of the Week are typed on the old page; the chat does not ask for them. */
export const FOCUS_ON_OLD_PAGE = "This section needs a topic and section titles, which are typed on the Focus page.";

export function draftCard(section: SectionSummary, mine: Drafting | null, config: AppConfig | null): DraftCard {
  if (!section.available) return { kind: "none", why: section.reason ?? "This section cannot be drafted yet." };
  const stopped = mine?.state === "failed" ? mine : null; // isLive narrows `mine` away from a failed entry, so read it first
  if (isLive(mine)) return { kind: mine.state === "queued" ? "queued" : "running", drafting: mine };
  if (section.needs_topic) return { kind: "blocked", why: FOCUS_ON_OLD_PAGE };
  if (config && providerOff(section.uses_provider, config)) return { kind: "blocked", why: config.provider_problem ?? "The drafting engine is not set up." };
  if (stopped) return { kind: "failed", why: stopped.reason ?? "The last draft stopped." };
  return { kind: "ready", again: section.latest !== null };
}
