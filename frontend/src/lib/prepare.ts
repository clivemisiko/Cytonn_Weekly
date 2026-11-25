import { inWorkbook } from "./analyst";
import { FETCHABLE_ITEMS, GROUPS, type Readiness, type ReadinessEntry } from "./chatcards";
import { snipCounts } from "./snips";
import { MAX_TOPIC, sectionTitles, sectionsProblem, topicLength } from "./topic";
import type { AnalystForm, AnalystItem, SnipsListing, SourcePiece } from "./types";

// ---- The prepare page's steps: every input of a section, in one fixed order, whether saved or not ----

export type StepKind = "item" | "fund" | "snips" | "sources" | "topic" | "titles";
export interface Step {
  /** A form item's key, "fund", "snips:<sector>", "sources", "topic" or "titles". */
  key: string;
  label: string;
  kind: StepKind;
}

/** The fund table's own form lines: they follow the fund table step, the table itself is the fund step. */
const FUND_KEYS = ["mmf_published", "mmf_source"];

const formItems = (form: AnalystForm | null) => (form?.groups ?? []).flatMap((g) => g.items);

/** The form's items as steps: names boxes first, then single values, then tables, then the fund table and its two lines.
 *  Tables the tool fetches are rows of card 1, not steps. `fund` false leaves the fund table out (the chat shows its own card). */
export function itemSteps(form: AnalystForm | null, fund: boolean): Step[] {
  const items = formItems(form);
  const step = (i: AnalystItem): Step => ({ key: i.key, label: i.label, kind: "item" });
  const fields = items.filter((i) => i.type === "field" && !FUND_KEYS.includes(i.key));
  const tables = items.filter((i) => i.type === "table" && i.key !== "mmf" && !(i.key in FETCHABLE_ITEMS));
  const hasFund = items.some((i) => i.key === "mmf");
  return [
    ...fields.filter((i) => i.type === "field" && i.kind === "names").map(step),
    ...fields.filter((i) => !(i.type === "field" && i.kind === "names")).map(step),
    ...tables.map(step),
    ...(hasFund && fund ? [{ key: "fund", label: "Money market fund table", kind: "fund" as const }] : []),
    ...items.filter((i) => FUND_KEYS.includes(i.key)).map(step),
  ];
}

/** Every step of a section's prepare page. Which ones a section has follows from its data alone: a form, snip sectors,
 *  a topic, sources. */
export function prepareSteps(opts: { form: AnalystForm | null; sectors: { id: string; label: string }[]; topic: boolean; sources: boolean }): Step[] {
  return [
    ...(opts.topic ? [{ key: "topic", label: "This week’s topic", kind: "topic" as const }, { key: "titles", label: "Section titles", kind: "titles" as const }] : []),
    ...itemSteps(opts.form, true),
    ...opts.sectors.map((s) => ({ key: `snips:${s.id}`, label: s.label, kind: "snips" as const })),
    ...(opts.sources ? [{ key: "sources", label: "Sources", kind: "sources" as const }] : []),
  ];
}

/** The form item a step stands for: the fund step is the fund table. */
export const itemKey = (step: Step) => (step.kind === "fund" ? "mmf" : step.key);

/** The keys of the steps this week's uploaded workbook already answers. The rule is the form's own status fields
 *  (`inWorkbook`: `workbook` / `workbook_rows`, which the API leaves empty for a missing workbook or one for another week,
 *  and which the readiness check reads as "from the workbook"); a table counts only when the workbook fills every one of its
 *  columns (the Eurobond issues' yield at issue is never in it), and a value waiting to be confirmed is never folded away. */
export function coveredKeys(steps: Step[], form: AnalystForm | null): string[] {
  const items = new Map(formItems(form).map((i) => [i.key, i] as const));
  return steps.flatMap((s) => {
    const i = s.kind === "item" || s.kind === "fund" ? items.get(itemKey(s)) : undefined;
    if (!i || i.needs_confirmation || !inWorkbook(i)) return [];
    const full = i.type === "field" || i.columns.every((c) => i.workbook_rows!.some((r) => r[c.key]));
    return full ? [s.key] : [];
  });
}

/** The steps still to go through and the ones folded into "from the workbook"; an overridden step goes back in its place. */
export function splitSteps(steps: Step[], covered: string[], overridden: string[] = []) {
  const folded = (s: Step) => covered.includes(s.key) && !overridden.includes(s.key);
  return { shown: steps.filter((s) => !folded(s)), folded: steps.filter(folded) };
}

/** Where the stepper stands once its steps change (a refold): the same step if it is still there, else the first one left. */
export function keepStep(before: string[], now: string[], at: number): number {
  const i = now.indexOf(before[at]);
  return i >= 0 ? i : 0;
}

/** The step an address names:a step's key, or "snips" for the first snip step. */
export const stepIndex = (steps: Step[], key: string | null | undefined) =>
  key ? steps.findIndex((s) => s.key === key || (key === "snips" && s.kind === "snips")) : -1;

/** Where the stepper opens: the step the address names, else the first one still missing, else the first. */
export function openingStep(steps: Step[], missing: string[], asked?: string | null): number {
  const named = stepIndex(steps, asked);
  if (named >= 0) return named;
  const first = steps.findIndex((s) => missing.includes(s.key));
  return first >= 0 ? first : 0;
}

// ---- Focus of the Week: the topic and titles typed on the page ----

/** What still stops a Focus draft, in words, by the start screen's own rules; empty when it can be drafted. */
export function focusProblems(topic: string, titles: string, bedrock: boolean): string[] {
  const out: string[] = [];
  if (!topic.trim()) out.push("the topic");
  else if (topicLength(topic) > MAX_TOPIC) out.push(`a topic of ${MAX_TOPIC} characters or fewer`);
  const titlesProblem = sectionsProblem(titles);
  if (titlesProblem) out.push("section titles within the limits");
  else if (bedrock && !sectionTitles(titles).length) out.push("the section titles");
  return out;
}

const focusKey = (period: string, section: string) => `cw-focus:${period}:${section}`;
/** The typed topic and titles, mirrored for a reload or a rail click. Storage may be missing or refuse: the page works without it. */
export function readFocus(period: string, section: string): { topic: string; titles: string } {
  try {
    const got = JSON.parse(sessionStorage.getItem(focusKey(period, section)) ?? "null") as unknown;
    if (got && typeof got === "object") {
      const { topic, titles } = got as Record<string, unknown>;
      return { topic: typeof topic === "string" ? topic : "", titles: typeof titles === "string" ? titles : "" };
    }
  } catch {
    /* no storage: start empty */
  }
  return { topic: "", titles: "" };
}
export function writeFocus(period: string, section: string, value: { topic: string; titles: string } | null) {
  try {
    if (value) sessionStorage.setItem(focusKey(period, section), JSON.stringify(value));
    else sessionStorage.removeItem(focusKey(period, section));
  } catch {
    /* the same */
  }
}

// ---- The counts: the banner, the checklist and the Create draft caption all come from here ----

export interface PrepareCounts {
  required: number;
  optional: number;
  /** The keys of steps still required, for where the stepper opens and what it calls still to do. */
  missing: string[];
  checklist: { key: string; heading: string; meaning: string; items: ReadinessEntry[] }[];
}

/** The readiness route's answer merged with what only the page knows: snips, sources and a Focus's topic and titles. */
export function prepareCounts(r: Readiness, page: { snips?: SnipsListing | null; sources?: SourcePiece[] | null; focus?: { topic: string; titles: string; bedrock: boolean } | null }): PrepareCounts {
  const extra: Record<string, ReadinessEntry[]> = { needs_analyst: [], optional: [], in_place: [] };
  if (page.snips) {
    const c = snipCounts(page.snips);
    for (const sec of page.snips.sectors) {
      const mine = page.snips.snips.filter((s) => s.sector === sec.id);
      const open = mine.filter((s) => !s.confirmed).length;
      const key = `snips:${sec.id}`;
      if (open) extra.needs_analyst.push({ kind: "snip", key, label: sec.label, why: `${open} ${open === 1 ? "snip" : "snips"} not confirmed` });
      else if (c.without.includes(sec.label)) extra.optional.push({ kind: "snip", key, label: sec.label, why: "no snip; left out of the draft" });
      else extra.in_place.push({ kind: "snip", key, label: sec.label, why: "confirmed" });
    }
  }
  for (const p of page.sources ?? []) {
    (p.sources.length ? extra.in_place : extra.optional).push({
      kind: "sources",
      key: "sources",
      label: `Sources for ${p.subject}`,
      why: p.sources.length ? `${p.sources.length} saved` : "none saved yet; gathered when drafting starts",
    });
  }
  if (page.focus) {
    const { topic, titles, bedrock } = page.focus;
    const topicOk = !!topic.trim() && topicLength(topic) <= MAX_TOPIC;
    (topicOk ? extra.in_place : extra.needs_analyst).push({ kind: "topic", key: "topic", label: "Topic", why: topicOk ? "typed" : topic.trim() ? "over the limit" : "not typed" });
    const n = sectionTitles(titles).length;
    const titlesBad = !!sectionsProblem(titles);
    const titlesEntry = { kind: "titles", key: "titles", label: "Section titles", why: titlesBad ? "over the limits" : n ? `${n} typed` : bedrock ? "not typed" : "not typed; the tool proposes them" };
    (titlesBad || (bedrock && !n) ? extra.needs_analyst : n ? extra.in_place : extra.optional).push(titlesEntry);
  }
  const checklist = GROUPS.map((g) => ({ ...g, items: [...r.groups[g.key], ...(extra[g.key] ?? [])] }));
  const of = (key: string) => checklist.find((g) => g.key === key)?.items ?? [];
  return {
    required: of("needs_analyst").length,
    optional: of("optional").length,
    missing: [...of("needs_analyst"), ...of("carried_or_suggested")].map((e) => e.key),
    checklist,
  };
}

export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The one line an empty card 1 shows, naming where this section's inputs go instead. */
export function noDocumentsLine(steps: Step[]): string {
  if (steps.some((s) => s.kind === "topic")) return "Nothing to upload here. The topic and section titles are typed in the next card.";
  if (steps.some((s) => s.kind === "snips")) return "Nothing to upload here. The snips are added in the next card.";
  return "Nothing to upload here. Anything this section needs is in the next card.";
}
export const NO_STEPS_LINE = "Nothing to type for this section.";
