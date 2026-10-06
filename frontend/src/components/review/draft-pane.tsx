import { WarningIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { SCOPE_LABELS, TABLE_COLUMNS, weekRange } from "@/lib/format";
import type { HighlightItem, Outlook, Review, Section, StockTableItem } from "@/lib/types";
import { DevAlert, Notice } from "./banners";
import { Markdown } from "./markdown";

/** The report's own roman numeral, as a fixed-width ink tile (an index column, so every headline starts at the same x). */
export function Numeral({ children }: { children: string }) {
  return (
    <span className="inline-grid h-6 w-8 shrink-0 place-items-center rounded-sm bg-primary font-mono text-xs font-semibold text-primary-foreground">
      {children}
    </span>
  );
}

export function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1">
      {items.map((w, i) => (
        <li key={`${i}-${w}`} className="flex items-start gap-2 text-sm text-warn-fg">
          <WarningIcon weight="bold" className="mt-0.5 size-4 shrink-0" aria-hidden />
          {w}
        </li>
      ))}
    </ul>
  );
}

type Part = { text: string; style?: "name" | "mono" };

/** Where a highlight came from, as one quiet line: company, search scope, domain, drafting model. */
function Provenance({ item }: { item: HighlightItem }) {
  const scope = SCOPE_LABELS[item.search_scope] ?? item.search_scope;
  const all: Part[] = [
    { text: item.company, style: "name" },
    { text: scope },
    { text: item.ir_domain ?? "", style: "mono" },
    { text: `Drafted by ${item.drafted_by}`, style: "mono" },
  ];
  const parts = all.filter((p) => p.text);
  return (
    <ul className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground md:pl-11">
      {parts.map((p, i) => (
        <li key={`${i}-${p.text}`} className="flex items-center gap-2">
          {i > 0 && <span aria-hidden>·</span>}
          <span className={cn(p.style === "name" && "font-semibold text-foreground", p.style === "mono" && "font-mono")}>{p.text}</span>
        </li>
      ))}
    </ul>
  );
}

function Highlight({ item }: { item: HighlightItem }) {
  return (
    <article className="space-y-3 border-t px-4 py-6 sm:px-6" aria-labelledby={`hl-${item.numeral}`}>
      <h3 id={`hl-${item.numeral}`} className="flex items-start gap-3 text-base font-semibold">
        <Numeral>{item.numeral}</Numeral>
        <span>{item.headline}</span>
      </h3>
      <Markdown className="max-w-[68ch] text-base leading-7 md:pl-11">{item.body_md}</Markdown>
      <Provenance item={item} />
      <div className="md:pl-11 empty:hidden">
        <Warnings items={item.warnings} />
      </div>
    </article>
  );
}

type Row = Record<string, unknown> & { flagged: boolean; error: string | null };

/**
 * A report table: headers wrap on wide screens and stay single-line (with sideways scroll) on a phone, figures
 * right-aligned in mono, a flagged row tinted with the checker's glyph in its first cell. Every section's
 * tables use this one component, so that behaviour is solved once.
 */
export function DataTable({
  id,
  title,
  columns,
  rows,
  rowKey,
}: {
  id: string;
  title: string;
  columns: { key: string; label: string; numeric: boolean }[];
  rows: Row[];
  rowKey: string;
}) {
  return (
    <div
      role="region"
      aria-label={`${title}, scrolls sideways on narrow screens`}
      tabIndex={0}
      className="overflow-x-auto rounded-md border focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <table className={cn("w-full border-collapse text-sm break-normal", columns.length > 5 ? "min-w-160" : "min-w-120")}>
        <caption className="sr-only">
          {title}. Rows the checker flagged are marked in the first column.
        </caption>
        <thead>
          <tr className="border-b bg-muted">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cn("eyebrow px-3 py-2 align-bottom whitespace-nowrap lg:whitespace-normal", c.numeric ? "text-right" : "text-left")}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-3 text-sm text-muted-foreground">
                No rows this week.
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr
              key={`${id}-${String(row[rowKey])}`}
              data-flagged={row.flagged || undefined}
              className="border-b transition-colors last:border-b-0 hover:bg-muted/60 data-flagged:bg-flag/10 data-flagged:font-semibold"
            >
              {columns.map((c, i) => (
                <td
                  key={c.key}
                  translate={c.numeric ? undefined : "no"}
                  className={cn(
                    "px-3 py-2 whitespace-nowrap",
                    c.numeric ? "text-right font-mono" : "text-left",
                    i === 0 && "font-medium",
                    c.key === "ticker" && "font-mono text-muted-foreground",
                    i === 0 && row.flagged && "shadow-[inset_6px_0_0_var(--flag)]",
                  )}
                >
                  {i === 0 && row.flagged && (
                    <span className="state-flagged mr-2 inline-flex align-middle">
                      <span className="glyph" title="Flagged by the checker">
                        <span className="sr-only">Flagged: </span>!
                      </span>
                    </span>
                  )}
                  {String(row[c.key] ?? "-")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StockTable({ item }: { item: StockTableItem }) {
  const failed = item.rows.filter((r) => r.error);
  return (
    <section className="space-y-3 border-t px-4 py-6 sm:px-6" aria-labelledby="stock-table-title">
      <h3 id="stock-table-title" className="flex items-center gap-3 text-base font-semibold">
        <Numeral>{item.numeral}</Numeral>
        {item.title}
      </h3>
      <DataTable id="stock" title={item.title} columns={TABLE_COLUMNS} rows={item.rows as unknown as Row[]} rowKey="ticker" />
      {failed.map((r) => (
        <p key={r.ticker} className="text-sm text-flag-fg">
          {r.ticker} failed to fetch: {r.error}
        </p>
      ))}
    </section>
  );
}

function OutlookBlock({ outlook }: { outlook: Outlook }) {
  return (
    <section className="space-y-4 border-t px-4 py-6 sm:px-6" aria-label="Outlook">
      <Markdown className="max-w-[68ch] text-base leading-7">{outlook.text_md}</Markdown>
      <dl className="max-w-md divide-y rounded-md border text-sm">
        {outlook.stats.map((s) => (
          <div key={s.key} className="flex items-baseline justify-between gap-6 px-3 py-2">
            <dt className="font-mono text-xs text-muted-foreground">{s.key}</dt>
            <dd className="text-right font-mono font-medium">{s.value}</dd>
          </div>
        ))}
      </dl>
      <Warnings items={outlook.warnings} />
    </section>
  );
}

/** The drafted section, for context while resolving items: highlights, the table, the outlook. */
export function DraftPane({ review, section: sec }: { review: Review; section: Section }) {
  const highlights = sec.items.filter((i): i is HighlightItem => i.kind === "highlight");
  const table = sec.items.find((i): i is StockTableItem => i.kind === "stock_table");
  return (
    <section aria-labelledby="draft-title" className="min-w-0 rounded-lg border bg-card [overflow-wrap:anywhere]">
      <div className="flex flex-col gap-3 px-4 py-4 sm:px-6">
        <h2 id="draft-title" className="text-lg font-semibold">
          Drafted section: {weekRange(sec.week_start, sec.week_end)}
        </h2>
        <div className="space-y-2 empty:hidden">
          {review.is_dev_draft && review.dev_mode_label && <DevAlert label={review.dev_mode_label} />}
          {sec.shortfall > 0 && (
            <Notice tone="warn" role="status" className="font-semibold">
              Only {sec.highlights_found} of {sec.highlights_expected} highlights were found this week.
            </Notice>
          )}
          {sec.warnings.map((w, i) => (
            <Notice key={`${i}-${w}`} tone="warn">
              {w}
            </Notice>
          ))}
        </div>
      </div>
      {highlights.map((h) => (
        <Highlight key={h.numeral} item={h} />
      ))}
      {table && <StockTable item={table} />}
      <OutlookBlock outlook={sec.outlook} />
    </section>
  );
}
