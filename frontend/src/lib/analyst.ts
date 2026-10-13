// The pure parts of the "Weekly analyst inputs" form (components/review/analyst/), kept apart
// from the components so they can be unit-tested.
import { friendlyDate } from "./format";
import type { AnalystCarried, AnalystColumn, AnalystField, AnalystRow, AnalystTable } from "./types";

/** Where an item's value comes from: typed here, the uploaded workbook, both and different, or nowhere. */
export type Origin = "typed" | "differs" | "workbook" | "empty" | "carried" | "unconfirmed";

export const range = (min: number | null, max: number | null, unit: string) =>
  min === null || max === null ? "" : `${min.toLocaleString()} to ${max.toLocaleString()}${unit === "%" || unit === "x" ? unit : unit ? ` ${unit}` : ""}`;

/** "carried from week ending 2 Oct 2026", or "suggested" for a worked-out running total. */
export const cameFrom = (carried: AnalystCarried) =>
  carried.from === "suggested" ? "suggested" : `carried from week ending ${friendlyDate(carried.from)}`;

export const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export const asText = (value: string | string[] | null | undefined) => (Array.isArray(value) ? value.join("\n") : (value ?? ""));

export const header = (col: AnalystColumn) => (col.unit ? `${col.label} (${col.unit})` : col.label);

export function fieldOrigin(item: AnalystField): Origin {
  if (item.needs_confirmation) return "unconfirmed";
  if (asText(item.value)) return item.differences.length ? "differs" : item.carried ? "carried" : "typed";
  return asText(item.workbook?.value) ? "workbook" : "empty";
}

export const tableOrigin = (item: AnalystTable): Origin =>
  item.needs_confirmation
    ? "unconfirmed"
    : item.rows?.length
      ? item.differences.length
        ? "differs"
        : item.carried?.whole
          ? "carried"
          : "typed"
      : item.workbook_rows?.length
        ? "workbook"
        : "empty";

/** The chip's words. `rows` is "12 rows" for a table and absent for a field. */
export function originLabel(origin: Origin, carried: AnalystCarried | null, rows?: string): string {
  const n = rows ? `, ${rows}` : "";
  if (origin === "unconfirmed" && carried) return `${capital(cameFrom(carried))}${n}, not confirmed`;
  if (origin === "carried" && carried) return `${capital(cameFrom(carried))}${n}`;
  if (origin === "typed") return `Typed${n}`;
  if (origin === "differs") return `Typed${n}, differs from the workbook`;
  if (origin === "workbook") return `From the workbook${n}`;
  return "Empty";
}

export interface Line {
  /** A given row's key, or a local id for a row of the open-ended grid. */
  id: string;
  label: string;
  typed: AnalystRow;
  /** What the row gets where nothing is typed: the uploaded workbook's value, else one the tool reads itself. */
  book: AnalystRow;
  /** True when the uploaded workbook lists the row (its name is then fixed). */
  listed: boolean;
}

export const nameKey = (name: string) => name.trim().replace(/\s+/g, " ").toLowerCase();

/** The grid's lines: the given rows, or the typed rows followed by the workbook's other rows. */
export function linesOf(item: AnalystTable): Line[] {
  const typed = item.rows ?? [];
  const book = item.workbook_rows ?? [];
  if (item.fixed_rows.length) {
    return item.fixed_rows.map((r) => ({
      id: r.key,
      label: r.label,
      typed: { ...(typed.find((t) => t.row === r.key) ?? {}) },
      book: book.find((b) => b.row === r.key) ?? {},
      listed: true,
    }));
  }
  const name = item.columns[0].key;
  const named = (rows: AnalystRow[], company: string) => rows.find((r) => nameKey(r[name] ?? "") === nameKey(company));
  // KCB IB's price for the Friday comes before the workbook's, as in the draft; the stored week's price fills what is left.
  const prefill = (company: string): AnalystRow => {
    const auto = named(item.auto_rows ?? [], company) ?? {};
    const fromBook = named(book, company) ?? {};
    return { ...auto, ...fromBook, ...(auto.price ? { price: auto.price } : {}) };
  };
  const lines: Line[] = typed.map((t, n) => ({
    id: `typed-${n}`,
    label: t[name] ?? "",
    typed: { ...t },
    book: prefill(t[name] ?? ""),
    listed: !!named(book, t[name] ?? ""),
  }));
  const seen = new Set(typed.map((t) => nameKey(t[name] ?? "")));
  book.forEach((b, n) => {
    if (!seen.has(nameKey(b[name] ?? ""))) lines.push({ id: `book-${n}`, label: b[name] ?? "", typed: {}, book: b, listed: true });
  });
  return lines;
}

/** The rows a grid sends: only what was typed. A workbook row nobody touched is not sent; the workbook supplies it. */
export function rowsOf(item: AnalystTable, lines: Line[]): AnalystRow[] {
  const fixed = item.fixed_rows.length > 0;
  const name = item.columns[0].key;
  const out: AnalystRow[] = [];
  for (const line of lines) {
    const row: AnalystRow = {};
    for (const col of item.columns) {
      const value = (line.typed[col.key] ?? "").trim();
      if (value) row[col.key] = value;
    }
    if (fixed) {
      if (Object.keys(row).length) out.push({ row: line.id, ...row });
      continue;
    }
    const company = row[name] ?? (Object.keys(row).length ? line.label : "");
    if (company) out.push({ ...row, [name]: company });
  }
  return out;
}

export const canonical = (item: AnalystTable, rows: AnalystRow[]) =>
  JSON.stringify(rows.map((r) => ["row", ...item.columns.map((c) => c.key)].map((k) => r[k] ?? "")));

/** Whether a cell still holds the value carried from last week's form (as saved; an edited cell no longer does). */
export function isCarried(item: AnalystTable, line: Line, key: string): boolean {
  const c = item.carried;
  if (!c) return false;
  const fixed = item.fixed_rows.length > 0;
  const saved = (item.rows ?? []).find((r) => (fixed ? r.row === line.id : nameKey(r[item.columns[0].key] ?? "") === nameKey(line.label)));
  if (!saved || saved[key] === undefined || (line.typed[key] ?? "") !== saved[key]) return false;
  return c.whole || (c.cells[fixed ? line.id : line.label] ?? []).includes(key);
}
