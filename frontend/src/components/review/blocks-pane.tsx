import { ChartBarIcon, LockSimpleIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { SCOPE_LABELS, friendlyDate, friendlyTime, weekRange } from "@/lib/format";
import type { BlocksSection, NarrativeBlock, NotCovered, Review, SuppliedBlock, TableBlock, UnavailableBlock } from "@/lib/types";
import { DevAlert, Notice } from "./banners";
import { DataTable, Numeral, Warnings } from "./draft-pane";
import { Markdown } from "./markdown";

type Part = { text: string; style?: "name" | "mono" };

function Provenance({ parts }: { parts: Part[] }) {
  const shown = parts.filter((p) => p.text);
  return (
    <ul className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground md:pl-11">
      {shown.map((p, i) => (
        <li key={`${i}-${p.text}`} className="flex items-center gap-2">
          {i > 0 && <span aria-hidden>·</span>}
          <span className={cn(p.style === "name" && "font-semibold text-foreground", p.style === "mono" && "font-mono")}>{p.text}</span>
        </li>
      ))}
    </ul>
  );
}

function Narrative({ block }: { block: NarrativeBlock }) {
  const scope = block.search_scope ? (SCOPE_LABELS[block.search_scope] ?? block.search_scope) : "";
  return (
    <article className="space-y-3 border-t px-4 py-6 sm:px-6" aria-labelledby={`blk-${block.id}`}>
      <h3 id={`blk-${block.id}`} className="flex items-start gap-3 text-base font-semibold">
        <Numeral>{block.numeral}</Numeral>
        <span>{block.headline}</span>
      </h3>
      <Markdown className="max-w-[68ch] text-base leading-7 md:pl-11">{block.body_md}</Markdown>
      <Provenance
        parts={[
          { text: block.topic, style: "name" },
          { text: scope },
          { text: block.preferred_domains.join(", "), style: "mono" },
          { text: `Drafted by ${block.drafted_by}`, style: "mono" },
        ]}
      />
      <div className="md:pl-11 empty:hidden">
        <Warnings items={block.warnings} />
      </div>
    </article>
  );
}

function Table({ block }: { block: TableBlock }) {
  const failed = block.rows.filter((r) => r.error);
  const src = block.source;
  const safeUrl = src.url && /^https?:\/\//.test(src.url) ? src.url : null;
  return (
    <section className="space-y-3 border-t px-4 py-6 sm:px-6" aria-labelledby={`blk-${block.id}`}>
      <h3 id={`blk-${block.id}`} className="flex items-center gap-3 text-base font-semibold">
        <Numeral>{block.numeral}</Numeral>
        {block.title}
      </h3>
      <DataTable id={block.id} title={block.title} columns={block.columns} rows={block.rows} rowKey={block.key_field} />
      <p className="text-xs text-muted-foreground">
        Source:{" "}
        {safeUrl ? (
          <a href={safeUrl} target="_blank" rel="noopener noreferrer" className="text-link underline decoration-link/40 underline-offset-2 hover:decoration-link">
            {src.name}
          </a>
        ) : (
          src.name
        )}
        {src.as_of && (
          <>
            {" "}
            · as of <span className="font-mono">{src.as_of.length === 10 ? friendlyDate(src.as_of) : friendlyTime(src.as_of)}</span>
          </>
        )}
      </p>
      {failed.map((r) => (
        <p key={String(r[block.key_field])} className="text-sm text-flag-fg">
          {String(r[block.columns[0].key])}: {r.error}
        </p>
      ))}
    </section>
  );
}

/** A part of the real report this tool cannot draft yet. Neutral, not a review-state colour: nothing was checked. */
function Unavailable({ block }: { block: UnavailableBlock }) {
  return (
    <section className="space-y-3 border-t px-4 py-6 sm:px-6" aria-labelledby={`blk-${block.id}`}>
      <h3 id={`blk-${block.id}`} className="flex flex-wrap items-center gap-3 text-base font-semibold">
        <Numeral>{block.numeral}</Numeral>
        {block.title}
        <span className="inline-flex items-center gap-1 rounded-full border border-input px-2 py-0.5 text-xs font-semibold text-muted-foreground">
          <LockSimpleIcon weight="bold" className="size-3" aria-hidden />
          Not available yet
        </span>
      </h3>
      <div className="space-y-2 rounded-md border bg-muted px-4 py-3 text-sm md:ml-11">
        <p>{block.reason}</p>
        <p className="text-muted-foreground">
          <span className="font-semibold text-foreground">Unblocked by:</span> {block.unblock}
        </p>
      </div>
    </section>
  );
}

/** Text the coordinator supplied (Company Updates), shown as written. Never drafted, never checked. */
function Supplied({ block }: { block: SuppliedBlock }) {
  return (
    <article className="space-y-3 border-t px-4 py-6 sm:px-6" aria-labelledby={`blk-${block.id}`}>
      <h3 id={`blk-${block.id}`} className="flex items-start gap-3 text-base font-semibold">
        <Numeral>{block.numeral}</Numeral>
        <span>{block.title}</span>
      </h3>
      <Markdown className="max-w-[68ch] text-base leading-7 md:pl-11">{block.body_md}</Markdown>
      <Provenance parts={[{ text: "Supplied by you", style: "name" }, { text: "Not drafted and not checked by the tool" }]} />
    </article>
  );
}

/**
 * The real issue's charts for this section. The tool does not draw them, so they are listed for the coordinator to
 * add by hand, with the issue they were read from. A note, not a review item: nothing here was drafted or checked.
 */
function ChartNotes({ charts, reference }: { charts: string[]; reference: string | null | undefined }) {
  return (
    <section aria-labelledby="charts-title" className="space-y-2 rounded-md border border-dashed bg-muted/50 px-4 py-3">
      <h3 id="charts-title" className="flex items-center gap-2 text-sm font-semibold">
        <ChartBarIcon weight="bold" className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        Charts to add by hand ({charts.length})
      </h3>
      <p className="text-xs text-muted-foreground">
        Not generated by the tool. Titles as printed in {reference ?? "the reference issue"}; update their period and data before
        publishing.
      </p>
      <ol className="list-decimal space-y-1 pl-5 text-sm marker:font-mono marker:text-xs marker:text-muted-foreground">
        {charts.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
    </section>
  );
}

/**
 * Executive Summary only: for each section it includes, what that section's approved review holds that the summary does
 * not carry (tables, parts not yet drafted, further narrative pieces), so the coordinator sees exactly what is uncovered.
 * A note, not a review item: it lists names and nothing here was drafted or checked.
 */
function NotCoveredNotes({ items }: { items: NotCovered[] }) {
  return (
    <section aria-labelledby="not-covered-title" className="space-y-3 rounded-md border border-dashed bg-muted/50 px-4 py-3">
      <h3 id="not-covered-title" className="text-sm font-semibold">
        Not covered by this summary
      </h3>
      <ul className="space-y-3">
        {items.map((s) => {
          const parts: [string, string[]][] = [
            ["Tables", s.tables],
            ["Parts not yet drafted", s.unavailable],
            ["Further pieces", s.further_pieces],
          ];
          const left = parts.filter(([, names]) => names.length > 0);
          const dev = s.dev_pieces ?? [];
          return (
            <li key={s.section} className="space-y-1">
              <p className="text-sm font-medium">
                {s.title} <span className="font-mono text-xs font-normal text-muted-foreground">run {s.run_id}</span>
              </p>
              {dev.length > 0 && (
                <Notice tone="flag" className="text-xs font-semibold">
                  Dev-mode draft: {dev.map((d) => `${d.piece} (${d.drafted_by})`).join("; ")}. This section&apos;s approval carries the
                  dev mark into the summary, though the summary may not quote that piece.
                </Notice>
              )}
              {left.length === 0 ? (
                <p className="text-xs text-muted-foreground">Nothing else in this section.</p>
              ) : (
                <dl className="space-y-1 text-sm">
                  {left.map(([label, names]) => (
                    <div key={label} className="grid gap-x-3 sm:grid-cols-[10rem_1fr]">
                      <dt className="eyebrow">{label}</dt>
                      <dd className="min-w-0">{names.join("; ")}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Every block-shaped section (all but the weekly Digital Payments): its blocks in report order, nothing derived here. */
export function BlocksPane({ review, section: sec }: { review: Review; section: BlocksSection }) {
  return (
    <section aria-labelledby="draft-title" className="min-w-0 rounded-lg border bg-card [overflow-wrap:anywhere]">
      <div className="flex flex-col gap-3 px-4 py-4 sm:px-6">
        <h2 id="draft-title" className="text-lg font-semibold">
          Drafted section: {weekRange(sec.week_start, sec.week_end)}
        </h2>
        {sec.topic && (
          <p className="text-sm">
            <span className="eyebrow mr-2">Topic</span>
            {sec.topic}
          </p>
        )}
        <div className="space-y-2 empty:hidden">
          {review.is_dev_draft && review.dev_mode_label && <DevAlert label={review.dev_mode_label} />}
          {sec.summary_note && (
            <Notice tone="info" role="status">
              {sec.summary_note}
            </Notice>
          )}
          {sec.shortfall > 0 && (
            <Notice tone="warn" role="status" className="font-semibold">
              Only {sec.pieces_found} of {sec.pieces_expected} drafted pieces were found {review.period ? `for ${review.period}` : "this week"}.
            </Notice>
          )}
          {sec.warnings.map((w, i) => (
            <Notice key={`${i}-${w}`} tone="warn">
              {w}
            </Notice>
          ))}
        </div>
        {sec.not_covered && sec.not_covered.length > 0 && <NotCoveredNotes items={sec.not_covered} />}
        {sec.chart_notes && sec.chart_notes.length > 0 && <ChartNotes charts={sec.chart_notes} reference={sec.chart_reference} />}
      </div>
      {sec.blocks.map((b) =>
        b.kind === "narrative" ? (
          <Narrative key={b.id} block={b} />
        ) : b.kind === "table" ? (
          <Table key={b.id} block={b} />
        ) : b.kind === "supplied" ? (
          <Supplied key={b.id} block={b} />
        ) : (
          <Unavailable key={b.id} block={b} />
        ),
      )}
    </section>
  );
}
