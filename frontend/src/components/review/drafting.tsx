"use client";

import { useEffect, useState } from "react";
import { CircleNotchIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import * as api from "@/lib/api";
import { elapsed, friendlyTime } from "@/lib/format";
import type { Drafting, Overview, ReportChoice } from "@/lib/types";
import { Notice } from "./banners";

const POLL_MS = 5_000;

/**
 * Re-reads the overview of the report on screen every few seconds while a draft is running on the server, so the
 * screen shows it finishing (and the run it saved) without a reload. Stops as soon as nothing is drafting; a failed
 * poll is simply retried.
 */
export function useDraftingPoll(
  drafting: Drafting | null,
  onOverview: (next: Overview) => void,
  report: ReportChoice,
  enabled = true,
) {
  const active = enabled && drafting !== null;
  const { type, period, kind } = report;
  useEffect(() => {
    if (!active) return;
    let live = true;
    const id = setInterval(async () => {
      try {
        const next = await api.getOverview({ type, period, kind });
        if (live) onOverview(next);
      } catch {
        /* the API blinked: try again next tick */
      }
    }, POLL_MS);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [active, onOverview, type, period, kind]);
}

/** Whether the running draft is this section of this report (the same slug drafts in several report types). */
export const isDraftingThis = (drafting: Drafting | null, slug: string, report: ReportChoice) =>
  drafting !== null &&
  drafting.slug === slug &&
  (drafting.report_type ?? "weekly") === report.type &&
  (drafting.period ?? "") === report.period;

/** The server's elapsed seconds, counted on locally between polls (the browser's clock never enters into it). */
export function useLiveElapsed(drafting: Drafting | null): number {
  const base = drafting?.elapsed_seconds ?? 0;
  const [extra, setExtra] = useState(0);
  useEffect(() => {
    if (!drafting) return;
    const received = Date.now();
    const id = setInterval(() => setExtra(Math.floor((Date.now() - received) / 1000)), 1000);
    return () => {
      clearInterval(id);
      setExtra(0); // each poll brings a fresh server count; count on from that
    };
  }, [drafting]);
  return base + extra;
}

/** Overview-level notice: which section is drafting, since when, and whether it looks stuck. */
export function DraftingBanner({ drafting }: { drafting: Drafting }) {
  const seconds = useLiveElapsed(drafting);
  if (drafting.stale) {
    return (
      <Notice tone="warn" role="status">
        <span className="font-semibold">{drafting.title} has been drafting for {elapsed(seconds)}</span> (started{" "}
        {friendlyTime(drafting.started_at)}), longer than any healthy draft takes. It looks stuck: the next draft started, in
        any section, replaces it, and its result will be discarded.
      </Notice>
    );
  }
  return (
    <div role="status" className="flex flex-col gap-2 rounded-lg border border-primary/40 bg-primary/10 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
      <span className="flex shrink-0 items-center gap-2 text-sm font-semibold whitespace-nowrap">
        <CircleNotchIcon weight="bold" className="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
        Drafting {drafting.title}
        <span className="font-mono font-medium tabular-nums text-muted-foreground">{elapsed(seconds)}</span>
      </span>
      <span className="text-sm text-muted-foreground">
        Started {friendlyTime(drafting.started_at)}. One draft runs at a time, across every section; it is saved and shows
        below when it finishes.
      </span>
    </div>
  );
}

/** Small chip on the drafting section's own card. */
export function DraftingChip({ drafting }: { drafting: Drafting }) {
  const seconds = useLiveElapsed(drafting);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap",
        drafting.stale ? "border-warn/40 bg-warn/10 text-warn-fg" : "border-primary/40 bg-primary/10 text-foreground",
      )}
    >
      <CircleNotchIcon weight="bold" className={cn("size-3", !drafting.stale && "animate-spin motion-reduce:animate-none")} aria-hidden />
      {drafting.stale ? "Looks stuck" : "Drafting now"}
      <span className="font-mono font-medium tabular-nums">{elapsed(seconds)}</span>
    </span>
  );
}
