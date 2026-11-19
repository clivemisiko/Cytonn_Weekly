const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown) => (typeof v === "string" ? v : "");
const num = (v: unknown) => (typeof v === "number" ? v : 0);
const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? v.filter(isObject) : []);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((s): s is string => typeof s === "string") : []);

/** Fewest funds the form's table takes (the API's own check says the same). */
export const MIN_FUNDS = 5;

export type Currency = "KES" | "USD" | "";
export interface FundRow {
  id: number;
  /** The name as the page prints it, or as the analyst corrected it. */
  name: string;
  currency: Currency;
  rate: string | null;
  /** keep: on the list; new: not decided; pending: a cell could not be read. */
  group: "keep" | "new" | "pending";
  listName: string | null;
  duplicate: boolean;
  /** The cells (name, currency, rate) the two readings did not agree on, or that are still empty. */
  unresolved: string[];
}
export interface Fix {
  name?: string;
  currency?: "KES" | "USD";
  rate?: string;
  ignore?: boolean;
}
export interface TypedFund {
  fund: string;
  rate: string;
}
export interface FundSnip {
  image: { sha256: string; type: string; size: number } | null;
  read: boolean;
  rows: FundRow[];
  leftOut: { id: number; name: string; why: string }[];
  ignored: { id: number; name: string }[];
  usd: number;
  typed: TypedFund[];
  notOnPage: string[];
  unresolved: number;
  newCount: number;
  kept: number;
  fixes: Record<string, Fix>;
  include: string[];
}

/** The API's answer, checked whole: null when it is not the shape this card draws. */
export function parseFundSnip(data: unknown): FundSnip | null {
  if (!isObject(data) || typeof data.read !== "boolean" || !Array.isArray(data.rows) || !isObject(data.settings)) return null;
  const img = isObject(data.image) && typeof data.image.sha256 === "string" ? { sha256: data.image.sha256, type: text(data.image.type), size: num(data.image.size) } : null;
  return {
    image: img,
    read: data.read,
    rows: list(data.rows).map((r) => ({
      id: num(r.id),
      name: text(r.name),
      currency: r.currency === "KES" || r.currency === "USD" ? r.currency : "",
      rate: typeof r.rate === "string" ? r.rate : null,
      group: r.group === "keep" || r.group === "new" ? r.group : "pending",
      listName: typeof r.list_name === "string" ? r.list_name : null,
      duplicate: r.duplicate === true,
      unresolved: strings(r.unresolved),
    })),
    leftOut: list(data.left_out).map((r) => ({ id: num(r.id), name: text(r.name), why: text(r.why) })),
    ignored: list(data.ignored).map((r) => ({ id: num(r.id), name: text(r.name) })),
    usd: num(data.usd),
    typed: list(data.typed).map((t) => ({ fund: text(t.fund), rate: text(t.rate) })),
    notOnPage: strings(data.not_on_page),
    unresolved: num(data.unresolved),
    newCount: num(data.new),
    kept: num(data.kept),
    fixes: isObject(data.fixes) ? (data.fixes as Record<string, Fix>) : {},
    include: strings(data.settings.include),
  };
}

/** What the analyst reads after a page is read: counts only, in words. */
export function countsLine(s: FundSnip): string {
  const rows = s.rows.length + s.leftOut.length + s.usd + s.ignored.length;
  return `${rows} rows read: ${s.kept} on the list, ${s.newCount} to decide, ${s.leftOut.length} left out, ${s.usd} dollar fund${s.usd === 1 ? "" : "s"} (not in the table).`;
}

const PUBLISHED = /^\d{4}-\d{2}-\d{2}$/;

/** Why "Use this table" is off, one reason each; empty when it can be pressed (the API still judges). */
export function whyNotYet(s: FundSnip, published: string): string[] {
  const out: string[] = [];
  if (s.unresolved) out.push(`${s.unresolved} row${s.unresolved === 1 ? " has" : "s have"} a cell to type or a row to ignore.`);
  if (s.newCount) out.push(`${s.newCount} fund${s.newCount === 1 ? "" : "s"} not on the list ${s.newCount === 1 ? "is" : "are"} still to decide.`);
  const twice = s.rows.filter((r) => r.duplicate).length;
  if (twice) out.push(`${twice} rows are the same list fund: ignore the extra ones.`);
  if (s.kept + s.typed.length < MIN_FUNDS) out.push(`The table needs at least ${MIN_FUNDS} funds.`);
  if (!PUBLISHED.test(published)) out.push("Enter the day the page was published.");
  return out;
}

/** The fund list editor's text: one name a line. */
export const listText = (names: string[]) => names.join("\n");
export const parseList = (value: string) => value.split(/\r?\n/).map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);

/** The corrections to send: the held ones with this row's change on top (an empty value removes that correction). */
export function withFix(fixes: Record<string, Fix>, id: number, patch: Fix): Record<string, Fix> {
  const one: Fix = { ...fixes[String(id)], ...patch };
  for (const k of Object.keys(one) as (keyof Fix)[]) if (one[k] === "" || one[k] === false) delete one[k];
  const next = { ...fixes };
  if (Object.keys(one).length) next[String(id)] = one;
  else delete next[String(id)];
  return next;
}

export const currencyWord = (c: Currency) => (c === "USD" ? "USD" : c === "KES" ? "Kenya Shilling" : "not read");
