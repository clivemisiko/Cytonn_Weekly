"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import * as api from "@/lib/api";
import type { AppConfig, Drafting, Overview, ReportChoice, ReportType, Review, SectionSummary } from "@/lib/types";
import { Notice } from "./banners";
import { Masthead } from "./masthead";
import { OverviewScreen } from "./overview-screen";
import { ReviewScreen } from "./review-screen";
import { StartScreen } from "./start-screen";

type Phase =
  | { name: "booting" }
  | { name: "unreachable"; message: string }
  | { name: "overview"; config: AppConfig; overview: Overview }
  | { name: "start"; config: AppConfig; section: SectionSummary; saved: Review | null; drafting: Drafting | null }
  | { name: "review"; review: Review };

const EASE = [0.23, 1, 0.32, 1] as const;

const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err));

const REPORT_TYPES: ReportType[] = ["weekly", "quarterly", "half_year", "annual", "companion"];

/** The report in the address bar (?report=quarterly&period=Q3'2026), so a reload stays on it. Weekly when absent. */
function reportFromUrl(): ReportChoice {
  if (typeof window === "undefined") return api.WEEKLY_REPORT;
  const q = new URLSearchParams(window.location.search);
  const type = q.get("report") as ReportType | null;
  if (!type || !REPORT_TYPES.includes(type)) return api.WEEKLY_REPORT;
  return { type, period: q.get("period") ?? "", kind: q.get("kind") };
}

/** A saved review to open straight away (?review=12): where a finished draft run's "Open review" lands. */
function reviewFromUrl(): number | null {
  if (typeof window === "undefined") return null;
  const id = Number(new URLSearchParams(window.location.search).get("review"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

function reportToUrl(report: ReportChoice) {
  const q = new URLSearchParams();
  if (report.type !== "weekly" || report.period) {
    q.set("report", report.type);
    if (report.period) q.set("period", report.period);
    if (report.kind) q.set("kind", report.kind);
  }
  const search = q.toString();
  window.history.replaceState(null, "", search ? `?${search}` : window.location.pathname);
}

/** The report as the API normalized it ("q3 2026" comes back as "Q3'2026"). */
const normalized = (overview: Overview): ReportChoice => ({
  type: overview.report.type,
  period: overview.report.period,
  kind: overview.report.kind,
});

function Booting() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <div className="h-28 border-b border-band-rule bg-band" />
      <div className="mx-auto w-full max-w-275 space-y-3 px-4 pt-8 sm:px-6">
        <Skeleton className="h-16 w-full" />
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
    </div>
  );
}

function Unreachable({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <>
      <Masthead title="Coordinator review" />
      <div className="mx-auto w-full max-w-275 px-4 py-8 sm:px-6">
        <div className="max-w-xl">
          <h2 className="text-lg font-semibold">The review API is not reachable</h2>
          <Notice role="alert" className="mt-4 font-medium">
            {message}
          </Notice>
          <p className="mt-4 text-sm text-muted-foreground">
            Start it from the repo root with <code className="rounded-sm bg-muted px-1 py-0.5 font-mono text-xs">uvicorn api.main:app --port 8000</code>.
            To point this app at another address, set <code className="rounded-sm bg-muted px-1 py-0.5 font-mono text-xs">NEXT_PUBLIC_API_URL</code>.
          </p>
          <Button className="mt-6" size="lg" onClick={onRetry}>
            Try again
          </Button>
        </div>
      </div>
    </>
  );
}

/**
 * The overview of one report's sections, one section's start screen, or one open review. Only the chosen report is
 * remembered here (and in the address bar): the server holds every review, so going back to the overview re-reads it.
 */
export function ReviewApp() {
  const [phase, setPhase] = useState<Phase>({ name: "booting" });
  const [report, setReport] = useState<ReportChoice>(api.WEEKLY_REPORT);
  // The chosen report for callbacks that run later (start screen, back to the overview); set wherever it changes.
  const reportRef = useRef(report);

  /** The chosen report's overview. A report in the address bar that no longer fits falls back to the weekly one. */
  const fetchOverview = useCallback(async (wanted: ReportChoice): Promise<Phase> => {
    try {
      const config = await api.getConfig();
      try {
        return { name: "overview", config, overview: await api.getOverview(wanted) };
      } catch (err) {
        if ((err as api.ApiError).status !== 422) throw err;
        return { name: "overview", config, overview: await api.getOverview(api.WEEKLY_REPORT) };
      }
    } catch (err) {
      return { name: "unreachable", message: messageOf(err) };
    }
  }, []);

  /** Show a phase; an overview also fixes the chosen report to what the API normalized, here and in the address bar. */
  const show = useCallback((next: Phase) => {
    if (next.name === "overview") {
      const now = normalized(next.overview);
      reportRef.current = now;
      setReport(now);
      reportToUrl(now);
    }
    setPhase(next);
  }, []);

  /** A section's start screen, with its current saved review (if any) offered for resume. */
  const fetchStart = useCallback(async (slug: string): Promise<Phase> => {
    try {
      const [config, overview] = await Promise.all([api.getConfig(), api.getOverview(reportRef.current)]);
      const section = overview.sections.find((s) => s.slug === slug);
      if (!section) return { name: "overview", config, overview };
      const run = section.latest;
      const saved = run && (run.current ?? run.this_week) ? await api.getReview(run.run_id) : null;
      return { name: "start", config, section, saved, drafting: overview.drafting };
    } catch (err) {
      return { name: "unreachable", message: messageOf(err) };
    }
  }, []);

  useEffect(() => {
    let live = true;
    const wanted = reportFromUrl();
    const reviewId = reviewFromUrl();
    /** The review named in the address bar, or the overview if it cannot be read. Closing it goes to its own report. */
    const boot = async (): Promise<Phase | null> => {
      if (reviewId === null) return null;
      try {
        const review = await api.getReview(reviewId);
        reportRef.current = { type: review.report_type, period: review.period, kind: wanted.kind };
        return { name: "review", review };
      } catch {
        return null;
      }
    };
    void boot().then(async (opened) => {
      if (opened) {
        if (live) setPhase(opened);
        return;
      }
      const next = await fetchOverview(wanted);
      if (live) show(next);
    });
    return () => {
      live = false;
    };
  }, [fetchOverview, show]);

  const home = useCallback(() => {
    setPhase({ name: "booting" });
    void fetchOverview(reportRef.current).then(show);
  }, [fetchOverview, show]);

  /** Switch the overview to another report. A period the API rejects stays in the picker with the API's reason. */
  const chooseReport = useCallback(
    async (next: ReportChoice): Promise<string | null> => {
      if (phase.name !== "overview") return null;
      try {
        show({ ...phase, overview: await api.getOverview(next) });
        return null;
      } catch (err) {
        return messageOf(err);
      }
    },
    [phase, show],
  );

  const openSection = useCallback(
    async (slug: string, resume: boolean) => {
      if (phase.name !== "overview") return;
      const run = phase.overview.sections.find((s) => s.slug === slug)?.latest;
      if (resume && run) {
        try {
          setPhase({ name: "review", review: await api.getReview(run.run_id) });
          return;
        } catch (err) {
          setPhase({ name: "unreachable", message: messageOf(err) });
          return;
        }
      }
      setPhase(await fetchStart(slug));
    },
    [phase, fetchStart],
  );

  /** A polled overview replaces the shown one in place (same phase, so no screen transition). */
  const refreshOverview = useCallback(
    (overview: Overview) => setPhase((p) => (p.name === "overview" ? { ...p, overview } : p)),
    [],
  );

  const key =
    phase.name === "review" ? `review-${phase.review.run_id}` : phase.name === "start" ? `start-${phase.section.slug}` : phase.name;

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence mode="wait" initial={false}>
        <motion.main
          id="main"
          tabIndex={-1}
          key={key}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, transition: { duration: 0.1 } }}
          transition={{ duration: 0.18, ease: EASE }}
        >
          {phase.name === "booting" && <Booting />}
          {phase.name === "unreachable" && <Unreachable message={phase.message} onRetry={home} />}
          {phase.name === "overview" && (
            <OverviewScreen
              overview={phase.overview}
              config={phase.config}
              report={report}
              onReport={chooseReport}
              onOpen={(slug, resume) => void openSection(slug, resume)}
              onOverview={refreshOverview}
            />
          )}
          {phase.name === "start" && (
            <StartScreen
              section={phase.section}
              config={phase.config}
              report={report}
              saved={phase.saved}
              drafting={phase.drafting}
              onOpen={(review) => setPhase({ name: "review", review })}
              onRecheck={async () => setPhase(await fetchStart(phase.section.slug))}
              onHome={home}
            />
          )}
          {phase.name === "review" && <ReviewScreen initial={phase.review} onClose={home} />}
        </motion.main>
      </AnimatePresence>
    </MotionConfig>
  );
}
