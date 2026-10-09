"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import * as api from "@/lib/api";
import { elapsed, friendlyTime, weekRange } from "@/lib/format";
import { MAX_TOPIC, topicLength } from "@/lib/topic";
import type { AppConfig, Drafting, Overview, ReportChoice, Review, SectionSummary } from "@/lib/types";
import { DevRibbon, Notice } from "./banners";
import { isDraftingThis, useDraftingPoll, useLiveElapsed } from "./drafting";
import { InputsPanel } from "./inputs-panel";
import { Masthead } from "./masthead";

/** The weekly sections worked out from the week's uploaded inputs. */
const USES_INPUTS = ["fixed_income", "equities"];

const EASE = [0.23, 1, 0.32, 1] as const;

const MAX_TEXT = 10_000;

/** A draft already running on the server (started from another tab, or before this screen was opened). */
function ServerDraftingNotice({ drafting, mine }: { drafting: Drafting; mine: boolean }) {
  const seconds = useLiveElapsed(drafting);
  const time = <span className="font-mono tabular-nums">{elapsed(seconds)}</span>;
  if (drafting.stale) {
    return (
      <Notice tone="warn" role="status">
        <span className="font-semibold">
          {mine ? "This section" : drafting.title} has been drafting for {time}
        </span>
        , longer than any healthy draft takes, and looks stuck. Starting a draft replaces it; its result will be discarded.
      </Notice>
    );
  }
  return (
    <Notice tone="info" role="status">
      <span className="font-semibold">
        {mine ? "This section is" : `${drafting.title} is`} drafting now ({time}, started {friendlyTime(drafting.started_at)}).
      </span>{" "}
      {mine
        ? "It is saved when it finishes, and this screen then offers it for review."
        : "Only one draft runs at a time, across every section; drafting here unlocks when it finishes."}
    </Notice>
  );
}

/** A short list from the real issue (its own headings, its charts), shown beside the run's steps. */
function FromTheReport({ title, items, note }: { title: string; items: string[]; note?: string }) {
  if (items.length === 0) return null;
  return (
    <section className="space-y-2 border-t pt-6">
      <h3 className="eyebrow">{title}</h3>
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      <ul className="list-disc space-y-1 pl-5 text-sm marker:text-input">
        {items.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
    </section>
  );
}

/**
 * One section's start: what a run does (the section's own steps, from the API), the report and period it is for, its
 * current saved review to resume, and the draft button. Focus of the Week also takes the coordinator's topic and
 * Company Updates their text; the tool never picks the one or writes the other.
 *
 * The draft button starts a run (POST /api/runs) and goes to its run view (/runs/{run_id}), which shows the draft's
 * real steps as they happen and then hands over to the review. Nothing here waits for the draft itself.
 */
export function StartScreen({
  section,
  config,
  report,
  saved,
  drafting: initialDrafting,
  week,
  onWeek,
  onOpen,
  onRecheck,
  onHome,
}: {
  section: SectionSummary;
  config: AppConfig;
  /** The report and period this section is drafted for (chosen on the overview). */
  report: ReportChoice;
  saved: Review | null;
  /** The draft running on the server when this screen was opened, if any. */
  drafting: Drafting | null;
  /** Weekly only: the Friday the report week ends on (the period's, or the latest Friday). */
  week: string | null;
  /** Choose another report week; the report on screen changes with it. */
  onWeek: (weekEnding: string) => void;
  onOpen: (review: Review) => void;
  onRecheck: () => Promise<void>;
  onHome: () => void;
}) {
  const steps = section.steps;
  const weekly = report.type === "weekly" && !report.period;
  const thisRun = weekly ? "this week’s" : `the ${report.period}`;
  const [topic, setTopic] = useState("");
  const [text, setText] = useState("");
  const inputMissing = (section.needs_topic && !topic.trim()) || (section.needs_text && !text.trim());
  // Counted as the API counts it (lib/topic.ts). Nothing is ever cut: an over-long topic stays whole and blocks the draft.
  const topicCount = topicLength(topic);
  const topicOver = section.needs_topic && topicCount > MAX_TOPIC;
  const router = useRouter();
  // True from the click until the run view takes over (the start call answers at once).
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState<{ message: string; lostConnection: boolean } | null>(null);
  // Company Updates and the Executive Summary call no LLM: no API budget, no key needed, no draft slot.
  const llm = section.uses_provider;
  const providerBlocked = llm && !!config.provider_problem;

  // A draft already running on the server (this section's or another's) blocks this one until it finishes.
  const [serverDrafting, setServerDrafting] = useState(initialDrafting);
  const watched = useRef(isDraftingThis(initialDrafting, section.slug, report));
  const onServerOverview = useCallback(
    (next: Overview) => {
      setServerDrafting(next.drafting);
      const wasMine = watched.current;
      watched.current = isDraftingThis(next.drafting, section.slug, report);
      if (wasMine && !watched.current) void onRecheck(); // offer what it saved
    },
    [section.slug, report, onRecheck],
  );
  useDraftingPoll(serverDrafting, onServerOverview, report, !drafting);
  const blocked = llm && serverDrafting !== null && !serverDrafting.stale;

  const draft = async () => {
    setError(null);
    setDrafting(true);
    try {
      const { run_id } = await api.startRun(section.slug, report, {
        topic: section.needs_topic ? topic.trim() : undefined,
        text: section.needs_text ? text.trim() : undefined,
        provider: llm ? config.provider : undefined,
      });
      router.push(`/runs/${run_id}`);
    } catch (err) {
      const e = err as api.ApiError;
      // No HTTP status means the answer never arrived (timeout, dropped connection): the run may have started
      // all the same, and it saves its draft when it finishes. A 409 means a draft is already running.
      setError({ message: e.message, lostConnection: llm && (e.status === null || e.status === 409) });
      setDrafting(false);
      if (llm && e.status === 409) {
        try {
          onServerOverview(await api.getOverview(report)); // show which draft holds the slot, and watch it finish
        } catch {
          /* the error above already says a draft is running */
        }
      }
    }
  };

  const recheck = async () => {
    setError(null);
    await onRecheck();
  };

  const items = saved?.review_items ?? [];
  const resolved = items.filter((i) => i.resolution !== null).length;
  const draftLabel = drafting
    ? "Starting…"
    : section.needs_text
      ? "Save your text as the section"
      : section.requires_approved
        ? `Compose ${thisRun} summary`
        : `Draft ${thisRun} section`;

  return (
    <>
      {config.dev_mode && <DevRibbon label={config.dev_mode_label} />}
      <div className={cn(config.dev_mode && "pt-7")}>
        <Masthead
          title={`${section.title}: coordinator review`}
          onHome={onHome}
          kicker={weekly ? undefined : `${report.period}: all sections`}
          meta={weekly ? undefined : <span className="font-mono">{report.period}</span>}
        >
          {weekly
            ? "Draft this week’s section, check it, and review it here."
            : `Draft ${thisRun} section, check it, and review it here.`}
        </Masthead>

        <div className="mx-auto w-full max-w-275 space-y-8 px-4 pt-8 pb-16 sm:px-6">
          {report.type === "weekly" && week && USES_INPUTS.includes(section.slug) && (
            <InputsPanel key={week} week={week} onWeek={onWeek} disabled={drafting} />
          )}
          <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-12">
            <div className="space-y-6">
              <section aria-labelledby="flow-title">
                <h2 id="flow-title" className="pb-4 text-lg font-semibold">
                  What a run does
                </h2>
                <ol>
                  {steps.map(({ title, body }, i) => {
                    const mine = i === steps.length - 1;
                    return (
                      <li
                        key={title}
                        className="relative flex gap-4 pb-6 last:pb-0 not-last:before:absolute not-last:before:top-7 not-last:before:bottom-1 not-last:before:left-3 not-last:before:w-px not-last:before:bg-input"
                      >
                        <span
                          className={cn(
                            "relative z-10 grid size-6 shrink-0 place-items-center rounded-sm border font-mono text-xs font-semibold",
                            mine ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card",
                          )}
                        >
                          {i + 1}
                        </span>
                        <div>
                          <p className="text-sm font-semibold">{title}</p>
                          <p className="text-sm text-muted-foreground">{body}</p>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
              <FromTheReport title="In the real report" items={section.subsections} />
              <FromTheReport
                title="Charts to add by hand"
                items={section.charts}
                note="The real issue carries these charts. The tool does not draw them; the review screen lists them again as a checklist."
              />
            </div>

            <section aria-labelledby="start-title" className="space-y-6 rounded-lg border border-t-[3px] border-t-primary bg-card p-6">
              <h2 id="start-title" className="sr-only">
                Start or resume a review
              </h2>

              {!weekly && (
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b pb-4 text-sm">
                  <p>
                    <span className="eyebrow mr-2">Report</span>
                    <span className="font-semibold">{report.period}</span>
                  </p>
                  <button
                    type="button"
                    onClick={onHome}
                    className="rounded-sm text-sm text-link underline decoration-link/40 underline-offset-2 outline-none hover:decoration-link focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Change report
                  </button>
                </div>
              )}

              {saved && (
                <div className="space-y-3 border-b pb-6">
                  {saved.decision === null ? (
                    <>
                      <p className="text-sm">
                        {weekly ? "This week’s" : `The ${report.period}`} review is in progress (run {saved.run_id},{" "}
                        {weekly ? "report week" : "period"} {weekRange(saved.section.week_start, saved.section.week_end)}):{" "}
                        <span className="font-mono">{resolved}</span> of <span className="font-mono">{items.length}</span> items resolved.
                        Resuming it does not re-run the draft.
                      </p>
                      <div className="h-2 overflow-hidden rounded-full bg-border" aria-hidden>
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${items.length ? (resolved / items.length) * 100 : 0}%` }}
                        />
                      </div>
                    </>
                  ) : (
                    <p className="text-sm">
                      {weekly ? "This week’s" : `The ${report.period}`} review (run {saved.run_id}) was {saved.decision}
                      {saved.decided_at ? ` on ${friendlyTime(saved.decided_at)}` : ""}.
                    </p>
                  )}
                  <Button size="lg" variant={saved.decision === null ? "default" : "outline"} onClick={() => onOpen(saved)} disabled={drafting}>
                    {saved.decision === null ? "Resume this review" : "View it"}
                  </Button>
                </div>
              )}

              <div className="space-y-3">
                <p className="text-sm">
                  {saved
                    ? "Or start over with a new draft. The saved review stays in the database either way."
                    : section.needs_text
                      ? `No ${section.title} saved ${weekly ? "this week" : `for ${report.period}`} yet. Paste the text below.`
                      : section.requires_approved
                        ? `Not composed ${weekly ? "this week" : `for ${report.period}`} yet. It is built only from sections you have approved.`
                        : `No review ${weekly ? "this week" : `for ${report.period}`} yet. Draft ${thisRun} ${section.title} section, check it, and review it here.`}
                </p>

                {providerBlocked && (
                  <Notice role="alert" className="font-medium">
                    {config.provider_problem} Drafting is off until then.
                  </Notice>
                )}
                {config.dev_mode && llm && (
                  <Notice role="alert" className="font-semibold">
                    CYTONN_LLM_PROVIDER=local: DEV MODE. Drafts from the local model are NOT FOR PUBLICATION.
                  </Notice>
                )}
                {llm && config.spends_api_budget && !config.provider_problem && (
                  <Notice tone="info">
                    Drafting provider: {config.provider}. A run spends real API budget (web search and tokens).
                  </Notice>
                )}
                {!llm && (
                  <Notice tone="info">
                    {section.needs_text
                      ? "Nothing is searched or drafted: your text is carried as written and listed once for you to accept."
                      : "Nothing is searched or drafted: each approved section’s lead piece is carried with its sources and checked again."}
                  </Notice>
                )}

                {serverDrafting && !drafting && llm && (
                  <ServerDraftingNotice drafting={serverDrafting} mine={isDraftingThis(serverDrafting, section.slug, report)} />
                )}

                {section.needs_topic && (
                  <div className="space-y-1">
                    <label htmlFor="focus-topic" className="text-sm font-semibold">
                      This week’s topic
                    </label>
                    <input
                      id="focus-topic"
                      name="topic"
                      type="text"
                      autoComplete="off"
                      value={topic}
                      disabled={drafting}
                      onChange={(e) => {
                        setTopic(e.target.value);
                        setError(null); // an error from the last attempt is about the topic as it was
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !inputMissing && !topicOver && !drafting && !blocked && !providerBlocked) void draft();
                      }}
                      placeholder="e.g. Sub-Saharan Africa Eurobonds performance…"
                      aria-invalid={topicOver || undefined}
                      aria-describedby="focus-topic-hint focus-topic-count"
                      className="flex h-10 w-full rounded-md border border-input bg-card px-3 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-flag md:text-sm"
                    />
                    <p id="focus-topic-hint" className="text-xs text-muted-foreground">
                      Your editorial call. The tool researches and drafts the topic you give it, with a source for every claim.
                    </p>
                    <p id="focus-topic-count" className={cn("text-xs", topicOver ? "font-medium text-flag-fg" : "text-muted-foreground")}>
                      <span className="font-mono tabular-nums">{topicCount.toLocaleString()}</span> of {MAX_TOPIC.toLocaleString()} characters.
                      {topicOver && (
                        <span role="status">
                          {" "}
                          Over the limit by <span className="font-mono tabular-nums">{(topicCount - MAX_TOPIC).toLocaleString()}</span>{" "}
                          {topicCount - MAX_TOPIC === 1 ? "character" : "characters"}. Shorten it to submit.
                        </span>
                      )}
                    </p>
                  </div>
                )}

                {section.needs_text && (
                  <div className="space-y-1">
                    <label htmlFor="supplied-text" className="text-sm font-semibold">
                      Your {section.title} text
                    </label>
                    <Textarea
                      id="supplied-text"
                      name="text"
                      rows={8}
                      maxLength={MAX_TEXT}
                      value={text}
                      disabled={drafting}
                      onChange={(e) => setText(e.target.value)}
                      placeholder={"Investment Updates:\n…\n\nHospitality Updates:\n…"}
                      aria-describedby="supplied-text-hint"
                      className="min-h-40 py-2"
                    />
                    <p id="supplied-text-hint" className="text-xs text-muted-foreground">
                      Cytonn’s own copy, as the real issue prints it under {section.subsections.map((h) => h.replace(/:$/, "")).join(" and ") || "this section"}. Markdown
                      links work. <span className="font-mono tabular-nums">{text.length.toLocaleString()}</span> of{" "}
                      {MAX_TEXT.toLocaleString()} characters.
                    </p>
                  </div>
                )}

                <Button
                  size="lg"
                  variant={saved ? "outline" : "default"}
                  disabled={drafting || blocked || providerBlocked || inputMissing || topicOver}
                  onClick={() => void draft()}
                >
                  {draftLabel}
                </Button>

                <AnimatePresence initial={false}>
                  {error && (
                    <motion.div
                      key="error"
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.2, ease: EASE }}
                      className="space-y-2"
                    >
                      <Notice role="alert" className="font-medium">
                        {error.message}
                      </Notice>
                      {error.lostConnection && (
                        <Button variant="outline" onClick={() => void recheck()}>
                          Check for a saved draft
                        </Button>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </section>
          </div>
        </div>
      </div>
    </>
  );
}
