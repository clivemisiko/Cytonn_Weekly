"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";
import { CheckIcon, CircleNotchIcon, MinusIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { DevAlert, DevRibbon, Notice } from "@/components/review/banners";
import { Masthead } from "@/components/review/masthead";
import * as api from "@/lib/api";
import { STATUS_META, STATUS_ORDER, friendlyTime, reportName } from "@/lib/format";
import { isTerminal, mergeEvents, overviewHref, stepLines, type StepLine } from "@/lib/run";
import type { AppConfig, Run, RunEvent, Status } from "@/lib/types";

const EASE = [0.23, 1, 0.32, 1] as const;
const POLL_MS = 2_000;
/** How close to the foot of the page counts as "following along". */
const FOLLOW_PX = 96;

const LINK = "rounded-sm text-link underline decoration-link/40 underline-offset-2 outline-none hover:decoration-link focus-visible:ring-2 focus-visible:ring-ring";

/**
 * How the events are arriving. `stream`: the EventSource is open. `poll`: it could not be opened, so the run is read
 * every two seconds instead. `lost`: it was open and dropped mid-run; the run is still read every two seconds, and
 * the notice stays until a read succeeds. None of them ever starts a run.
 */
type Feed = "connecting" | "stream" | "poll" | "lost";

function Mark({ line, still }: { line: StepLine; still: boolean }) {
  const box = "grid size-5 shrink-0 place-items-center rounded-full";
  if (line.mark === "failed") {
    return (
      <span className="state-flagged" aria-hidden>
        <span className="glyph">!</span>
      </span>
    );
  }
  if (line.mark === "skipped") {
    return (
      <span className={cn(box, "border border-dashed border-input text-muted-foreground")} aria-hidden>
        <MinusIcon weight="bold" className="size-3" />
      </span>
    );
  }
  if (line.mark === "done") {
    return (
      <span className={cn(box, "border border-input text-foreground")} aria-hidden>
        <CheckIcon weight="bold" className="size-3" />
      </span>
    );
  }
  // Working: it spins only while it is the run's latest unfinished step and this screen is still hearing from the
  // run; never under reduced motion, and not once the connection is lost (the step may or may not be going on).
  return (
    <span className={cn(box, "text-foreground")} aria-hidden>
      <CircleNotchIcon weight="bold" className={cn("size-4", line.active && !still && "animate-spin")} />
    </span>
  );
}

const MARK_WORD: Record<StepLine["mark"], string> = { working: "In progress", done: "Done", skipped: "Skipped", failed: "Failed" };

function Step({ line, reduced, still }: { line: StepLine; reduced: boolean; still: boolean }) {
  return (
    <motion.li
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: EASE }}
      className="flex items-start gap-3 border-b px-4 py-3 last:border-b-0"
    >
      <Mark line={line} still={still} />
      <p className={cn("min-w-0 text-sm wrap-break-word", line.mark === "skipped" && "text-muted-foreground", line.mark === "failed" && "font-medium")}>
        <span className="sr-only">{MARK_WORD[line.mark]}: </span>
        {line.text}
      </p>
    </motion.li>
  );
}

/** One count, in the tile the review screen's scorecard uses for the same status. */
function CountTile({ status, value }: { status: Status; value: number }) {
  const meta = STATUS_META[status];
  return (
    <div className={cn("surface-state flex flex-col gap-2 p-4", `state-${status}`)}>
      <div className="flex items-center gap-2">
        <span className="glyph" aria-hidden>
          {meta.glyph}
        </span>
        <span className="eyebrow text-(--hue-fg)">{meta.label}</span>
      </div>
      <span className="font-mono text-2xl leading-none font-semibold tracking-tight">{value}</span>
      <p className="text-xs text-muted-foreground">{meta.hint}</p>
    </div>
  );
}

function Shell({ title, children, onHome }: { title: string; children: React.ReactNode; onHome: () => void }) {
  return (
    <main id="main" tabIndex={-1}>
      <Masthead title={title} onHome={onHome} />
      <div className="mx-auto w-full max-w-275 px-4 pt-8 pb-16 sm:px-6">
        <div className="max-w-3xl space-y-6">{children}</div>
      </div>
    </main>
  );
}

/**
 * One draft run as it happens: the section and report at the top, a status line, the run's steps, and (when it
 * ends) the result. Every line is an event the pipeline reported (lib/run.ts holds the wording); nothing is timed,
 * estimated or filled in, so when nothing is happening nothing on this screen moves. The run is only ever read
 * here: no code path on this screen starts one or retries one.
 */
export function RunView({ runId }: { runId: string }) {
  const router = useRouter();
  const reduced = useReducedMotion() ?? false;
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [missing, setMissing] = useState(false);
  const [feed, setFeed] = useState<Feed>("connecting");
  const [config, setConfig] = useState<AppConfig | null>(null);

  const ended = events.some(isTerminal);
  // The saved review's id and dev mark come with the run itself, which is read once more after its last event.
  const settled = run !== null && run.status !== "running";

  /** Read the run once. A 404 means the API no longer has it; any other failure leaves the screen as it is. */
  const read = useCallback(async (): Promise<boolean> => {
    try {
      const next = await api.getRun(runId);
      setRun(next);
      setEvents((have) => mergeEvents(have, next.events));
      return true;
    } catch (err) {
      if ((err as api.ApiError).status === 404) setMissing(true);
      return false;
    }
  }, [runId]);

  // The drafting provider, for the DEV MODE ribbon while a development draft is still running.
  useEffect(() => {
    let live = true;
    api.getConfig().then(
      (c) => live && setConfig(c),
      () => {},
    );
    return () => {
      live = false;
    };
  }, []);

  // First the run itself (who it is, what it has reported so far, or that it is gone), then its live stream.
  useEffect(() => {
    let live = true;
    let source: EventSource | null = null;
    void (async () => {
      const ok = await read();
      if (!live) return;
      if (!ok) {
        setFeed("lost"); // unreachable just now (a missing run stops everything below by itself)
        return;
      }
      let opened = false;
      source = new EventSource(api.runEventsUrl(runId));
      source.onopen = () => {
        opened = true;
        setFeed("stream");
      };
      source.addEventListener("step", (message) => {
        const event = JSON.parse((message as MessageEvent<string>).data) as RunEvent;
        setEvents((have) => mergeEvents(have, [event]));
        if (isTerminal(event)) source?.close(); // the server closes too; do not let the browser reconnect
      });
      source.onerror = () => {
        // Never let EventSource reconnect by itself: read the run plainly instead, every two seconds.
        source?.close();
        setFeed(opened ? "lost" : "poll");
      };
    })();
    return () => {
      live = false;
      source?.close();
    };
  }, [runId, read]);

  // Plain reads: while the stream is not carrying the run, and once after its last event for the saved review.
  const reading = !missing && !settled && (feed === "poll" || feed === "lost" || ended);
  useEffect(() => {
    if (!reading) return;
    let live = true;
    const tick = async () => {
      const ok = await read();
      if (live && ok) setFeed((f) => (f === "lost" ? "poll" : f)); // the API answers again
    };
    if (ended) void tick();
    const id = setInterval(() => void tick(), POLL_MS);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [reading, ended, read]);

  const lines = useMemo(() => stepLines(events), [events]);
  const last = events[events.length - 1];
  const final = events.find(isTerminal);

  // Keep the newest line in view, but only for someone already at the foot of the page: scrolling up to read
  // an earlier step is never undone.
  const following = useRef(true);
  const foot = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onScroll = () => {
      following.current = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - FOLLOW_PX;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    if (following.current) foot.current?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }, [lines.length, settled, reduced]);

  const home = useCallback(
    () => router.push(run ? overviewHref(run.report_type, run.period) : "/overview"),
    [router, run],
  );

  if (missing) {
    return (
      <Shell title="Draft run" onHome={home}>
        <Notice tone="warn" role="status">
          This run is no longer available. If the draft finished, open the section from the overview.{" "}
          <Link href="/overview" className={LINK}>
            Go to the overview
          </Link>
        </Notice>
      </Shell>
    );
  }

  const dev = run?.is_dev_draft === true || (config?.dev_mode === true && !settled);
  const devLabel = run?.dev_mode_label ?? config?.dev_mode_label ?? "";
  const weekly = run ? run.report_type === "weekly" && !run.period : true;
  const backHref = run ? overviewHref(run.report_type, run.period) : "/overview";
  const failed = final?.kind === "run_failed";

  let status: string;
  if (!last) status = run ? "Waiting for the draft to start." : feed === "lost" ? "Not connected." : "Loading the run…";
  else if (final) status = `${failed ? "Stopped" : "Finished"} ${friendlyTime(final.at)}.`;
  else status = `Running. Started ${friendlyTime(events[0].at)}.`;

  return (
    <>
      {dev && devLabel && <DevRibbon label={devLabel} />}
      <div className={cn(dev && devLabel && "pt-7")}>
        <main id="main" tabIndex={-1}>
          <Masthead
            title={run ? `${run.section_title}: draft run` : "Draft run"}
            onHome={home}
            kicker={weekly ? undefined : `${run!.period}: all sections`}
            meta={run && !weekly ? <span className="font-mono">{run.period}</span> : undefined}
          >
            {run ? `${reportName(run.report_title, run.period)}. Each line below is a step the draft has really taken.` : undefined}
          </Masthead>

          <div className="mx-auto w-full max-w-275 px-4 pt-8 pb-16 sm:px-6">
            <div className="max-w-3xl space-y-6">
              <p role="status" className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                <span className="font-semibold">{status}</span>
                {!final && feed === "poll" && <span className="text-muted-foreground">Live updates are off; checking every 2 seconds.</span>}
              </p>

              {feed === "lost" && !settled && (
                <Notice tone="warn" role="alert">
                  Connection lost. The draft may still finish. Check the overview before starting another.{" "}
                  <Link href={backHref} className={LINK}>
                    Go to the overview
                  </Link>
                </Notice>
              )}

              <section aria-labelledby="steps-title">
                <h2 id="steps-title" className="eyebrow pb-2">
                  Steps
                </h2>
                {/* Empty until the first event arrives: no placeholder moves while nothing has happened. */}
                <ol role="log" aria-label="Steps of this draft" className={cn("rounded-lg border bg-card", lines.length === 0 && "hidden")}>
                  {lines.map((line) => (
                    <Step key={line.key} line={line} reduced={reduced} still={reduced || feed === "lost"} />
                  ))}
                </ol>
                {lines.length === 0 && <p className="text-sm text-muted-foreground">No steps yet.</p>}
              </section>

              {final?.kind === "run_finished" && (
                <motion.section
                  aria-labelledby="result-title"
                  initial={reduced ? false : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.18, ease: EASE }}
                  className="space-y-4 rounded-lg border border-t-[3px] border-t-primary bg-card p-6"
                >
                  <h2 id="result-title" className="text-lg font-semibold">
                    Draft ready for review
                  </h2>
                  {run?.is_dev_draft && run.dev_mode_label && <DevAlert label={run.dev_mode_label} />}
                  <div role="group" aria-label="Review items by status" className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    {STATUS_ORDER.map((s) => (
                      <CountTile key={s} status={s} value={final.counts?.[s] ?? 0} />
                    ))}
                  </div>
                  {run?.review_id != null ? (
                    <Button asChild size="lg">
                      <Link href={overviewHref(run.report_type, run.period, run.review_id)}>Open review</Link>
                    </Button>
                  ) : (
                    <Button size="lg" disabled>
                      Open review
                    </Button>
                  )}
                </motion.section>
              )}

              {failed && (
                <div className="space-y-3">
                  <Notice role="alert" className="font-medium">
                    The draft stopped.{final.detail ? ` ${final.detail}` : ""}
                  </Notice>
                  <p className="text-sm">
                    <Link href={backHref} className={LINK}>
                      Back to overview
                    </Link>
                  </p>
                </div>
              )}

              <div ref={foot} aria-hidden />
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
