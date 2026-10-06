"use client";

import { CaretRightIcon, LockSimpleIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { friendlyDate, plural, reportName, weekRange } from "@/lib/format";
import type { AppConfig, Drafting, Overview, ReportChoice, SectionSummary } from "@/lib/types";
import { DevRibbon, Notice } from "./banners";
import { DraftingBanner, DraftingChip, isDraftingThis, useDraftingPoll } from "./drafting";
import { Masthead } from "./masthead";
import { ReportPicker } from "./report-picker";

type State = "approved" | "rejected" | "in_review" | "not_drafted" | "unavailable";

function stateOf(s: SectionSummary): State {
  if (!s.available) return "unavailable";
  const run = s.latest;
  if (!run || !(run.current ?? run.this_week)) return "not_drafted";
  if (run.decision === "approved") return "approved";
  if (run.decision === "rejected") return "rejected";
  return "in_review";
}

const CHIP: Record<State, { label: string; className: string; glyph?: string; stateClass?: string }> = {
  approved: { label: "Approved", className: "border-ok/40 bg-ok/10 text-ok-fg", glyph: "✓", stateClass: "state-clean" },
  rejected: { label: "Rejected", className: "border-flag/40 bg-flag/10 text-flag-fg", glyph: "!", stateClass: "state-flagged" },
  in_review: { label: "In review", className: "border-primary/40 bg-primary/10 text-foreground" },
  not_drafted: { label: "Not drafted this week", className: "border-input text-muted-foreground" },
  unavailable: { label: "Not available yet", className: "border-input bg-muted text-muted-foreground" },
};

/** "this week" for the unlabelled weekly report, "for Q3'2026" once a period is chosen. */
const when = (period: string) => (period ? `for ${period}` : "this week");

function StateChip({ state, period }: { state: State; period: string }) {
  const c = CHIP[state];
  const label = state === "not_drafted" ? `Not drafted ${when(period)}` : c.label;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap", c.className, c.stateClass)}>
      {c.glyph && (
        <span className="glyph size-4 text-xs" aria-hidden>
          {c.glyph}
        </span>
      )}
      {state === "unavailable" && <LockSimpleIcon weight="bold" className="size-3" aria-hidden />}
      {label}
    </span>
  );
}

function Progress({ s, period }: { s: SectionSummary; period: string }) {
  const run = s.latest!;
  const { resolved, total } = run.progress;
  const flagged = run.counts.flagged.total;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
        <span>
          <span className="font-mono font-semibold">{resolved}</span> of <span className="font-mono font-semibold">{total}</span> items
          resolved
        </span>
        {flagged > 0 && (
          <span className="state-flagged inline-flex items-center gap-1 text-xs font-semibold text-(--hue-fg)">
            <span className="glyph size-4 text-xs" aria-hidden>
              !
            </span>
            {flagged} flagged
          </span>
        )}
      </div>
      <div
        role="progressbar"
        aria-label={`${s.title}: items resolved`}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={resolved}
        className="h-2 overflow-hidden rounded-full bg-border"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${total ? (resolved / total) * 100 : 0}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">
        Run <span className="font-mono">{run.run_id}</span>
        {run.week_start && run.week_end ? `, ${period ? "period" : "report week"} ${weekRange(run.week_start, run.week_end)}` : ""}
        {run.topic ? `. Topic: ${run.topic}` : ""}
      </p>
    </div>
  );
}

function SectionRow({
  s,
  index,
  period,
  drafting,
  onOpen,
}: {
  s: SectionSummary;
  index: number;
  period: string;
  /** Set only on the card of the section being drafted right now. */
  drafting: Drafting | null;
  onOpen: (slug: string, resume: boolean) => void;
}) {
  const state = stateOf(s);
  const run = s.latest;
  const current = Boolean(run && (run.current ?? run.this_week));
  const draftLabel = s.needs_text ? "Add your text" : s.requires_approved ? "Compose summary" : "Draft section";
  const action =
    state === "unavailable"
      ? null
      : state === "in_review"
        ? { label: "Resume review", resume: true, primary: true }
        : state === "not_drafted"
          ? { label: draftLabel, resume: false, primary: true }
          : { label: "View review", resume: true, primary: false };

  return (
    <li
      className={cn(
        "grid grid-cols-[2rem_minmax(0,1fr)] gap-x-4 gap-y-3 rounded-lg border bg-card p-4 sm:p-6 md:grid-cols-[2rem_minmax(0,14rem)_minmax(0,1fr)_auto] md:items-start",
        state === "unavailable" && "bg-muted/50",
      )}
      aria-labelledby={`sec-${s.slug}`}
    >
      <span className="inline-grid h-6 w-8 place-items-center rounded-sm bg-primary font-mono text-xs font-semibold text-primary-foreground" aria-hidden>
        {index + 1}
      </span>

      <div className="min-w-0 space-y-2">
        <h2 id={`sec-${s.slug}`} className="text-base font-semibold">
          {s.title}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <StateChip state={state} period={period} />
          {drafting && <DraftingChip drafting={drafting} />}
          {current && run?.is_dev_draft && (
            <span className="hatch-dev rounded-sm px-1.5 py-0.5 font-mono text-xs font-semibold text-[#2a0a07]">DEV DRAFT</span>
          )}
        </div>
      </div>

      <div className="col-start-2 min-w-0 md:col-start-3">
        {state === "unavailable" ? (
          <div className="space-y-2 text-sm">
            <p>{s.reason}</p>
            <p className="text-muted-foreground">
              <span className="font-semibold text-foreground">Unblocked by:</span> {s.unblock}
            </p>
            {s.built_parts.length > 0 && (
              <div>
                <p className="eyebrow pb-1">Already built</p>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground marker:text-input">
                  {s.built_parts.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : run && current ? (
          <Progress s={s} period={period} />
        ) : (
          <p className="text-sm text-muted-foreground">
            {drafting
              ? drafting.stale
                ? "A draft has run far longer than it should and looks stuck. Drafting again replaces it."
                : "Drafting now; the review shows here when it finishes."
              : `Nothing drafted ${when(period)}.`}
            {run ? ` The last review (run ${run.run_id}, ${friendlyDate(run.run_date)}) was ${run.decision ?? "left in progress"}.` : ""}
            {s.needs_topic ? " Drafting asks for this week’s topic." : ""}
            {s.needs_text ? " You paste this section’s text; the tool never drafts Cytonn’s own copy." : ""}
            {s.requires_approved ? " Composed from the other sections once every one of them is approved." : ""}
          </p>
        )}
      </div>

      {action && (
        <div className="col-start-2 md:col-start-4 md:justify-self-end">
          <Button size="lg" variant={action.primary ? "default" : "outline"} onClick={() => onOpen(s.slug, action.resume)}>
            {action.label}
            <CaretRightIcon weight="bold" data-icon="inline-end" aria-hidden />
          </Button>
        </div>
      )}
    </li>
  );
}

function Tally({ overview }: { overview: Overview }) {
  const states = overview.sections.map(stateOf);
  const n = (st: State) => states.filter((x) => x === st).length;
  const cells: [string, number][] = [
    ["Approved", n("approved")],
    ["In review", n("in_review")],
    ["Not drafted", n("not_drafted")],
    ["Rejected", n("rejected")],
    ["Not available yet", n("unavailable")],
  ];
  return (
    <dl role="group" aria-label="Sections by state" className="grid grid-cols-2 divide-border rounded-lg border bg-card sm:grid-cols-5 sm:divide-x">
      {cells.map(([label, value]) => (
        <div key={label} className="flex flex-col gap-1 px-4 py-3 last:col-span-2 sm:last:col-span-1">
          <dt className="eyebrow">{label}</dt>
          <dd className="font-mono text-xl font-semibold">
            {value}
            <span className="text-sm font-medium text-muted-foreground"> / {states.length}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Every section of the chosen report at a glance; each one is reviewed and decided on its own. */
export function OverviewScreen({
  overview,
  config,
  report,
  onReport,
  onOpen,
  onOverview,
}: {
  overview: Overview;
  config: AppConfig;
  /** The report on screen, as the API normalized it. */
  report: ReportChoice;
  /** Switch to another report: resolves to an error to show in the picker, or null once switched. */
  onReport: (next: ReportChoice) => Promise<string | null>;
  onOpen: (slug: string, resume: boolean) => void;
  /** A fresher overview, from polling while a draft runs on the server. */
  onOverview: (next: Overview) => void;
}) {
  const { drafting } = overview;
  useDraftingPoll(drafting, onOverview, report);
  const name = reportName(overview.report.title, overview.report.period);
  const kind = overview.companion_kinds.find((k) => k.slug === overview.report.kind);
  return (
    <>
      {config.dev_mode && <DevRibbon label={config.dev_mode_label} />}
      <div className={cn(config.dev_mode && "pt-7")}>
        <Masthead title="Coordinator review" meta={<>Today {friendlyDate(overview.today)}</>}>
          {kind ? `${kind.title}: ` : `${name}: `}
          {plural(overview.sections.length, "report section")}. Each is drafted, checked and approved or rejected on its own.
        </Masthead>
        <div className="mx-auto w-full max-w-275 space-y-6 px-4 pt-8 pb-16 sm:px-6">
          <ReportPicker
            key={`${report.type}|${report.period}|${report.kind ?? ""}`}
            current={report}
            types={overview.report_types}
            kinds={overview.companion_kinds}
            onApply={onReport}
          />
          {config.dev_mode && (
            <Notice role="alert" className="font-semibold">
              CYTONN_LLM_PROVIDER=local: DEV MODE. Drafts from the local model are NOT FOR PUBLICATION.
            </Notice>
          )}
          {drafting && <DraftingBanner drafting={drafting} />}
          {overview.report.type === "companion" && (
            <Notice tone="info">
              Companion research reports ride inside a weekly issue as its Focus of the Week. Every section below is Cytonn’s own
              analysis, so none can be drafted yet; the weekly Focus of the Week can still draft a cited piece on the same topic.
            </Notice>
          )}
          <Tally overview={overview} />
          <ol className="space-y-3">
            {overview.sections.map((s, i) => (
              <SectionRow
                key={s.slug}
                s={s}
                index={i}
                period={overview.report.period}
                drafting={isDraftingThis(drafting, s.slug, report) ? drafting : null}
                onOpen={onOpen}
              />
            ))}
          </ol>
        </div>
      </div>
    </>
  );
}
