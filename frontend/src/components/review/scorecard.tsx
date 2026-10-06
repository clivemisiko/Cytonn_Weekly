"use client";

import { AnimatePresence, motion } from "motion/react";
import { cn } from "cn";
import { STATUS_META, STATUS_ORDER } from "@/lib/format";
import type { Review, Status, StatusCounts } from "@/lib/types";

const EASE = [0.23, 1, 0.32, 1] as const;

function subline(c: StatusCounts): string {
  if (c.total === 0) return "None in this draft";
  const parts = [c.unresolved ? `${c.unresolved} unresolved` : "", c.fix_needed ? `${c.fix_needed} fix needed` : ""].filter(Boolean);
  return parts.length ? parts.join(", ") : "All accepted";
}

function Tile({ status, counts }: { status: Status; counts: StatusCounts }) {
  const meta = STATUS_META[status];
  const sub = subline(counts);
  return (
    <div className={cn("surface-state flex flex-col gap-2 p-4", `state-${status}`)}>
      <div className="flex items-center gap-2">
        <span className="glyph" aria-hidden>
          {meta.glyph}
        </span>
        <span className="eyebrow text-(--hue-fg)">{meta.label}</span>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-2xl leading-none font-semibold tracking-tight">{counts.total}</span>
        <span className="relative min-h-5 text-sm font-medium">
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={sub}
              className="block"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4, transition: { duration: 0.1 } }}
              transition={{ duration: 0.16, ease: EASE }}
            >
              {sub}
            </motion.span>
          </AnimatePresence>
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{meta.hint}</p>
    </div>
  );
}

/** Three counts, one per status, in the same colour, glyph and border style the item cards use. */
export function Scorecard({ review }: { review: Review }) {
  return (
    <div role="group" aria-label="Review items by status" className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {STATUS_ORDER.map((s) => (
        <Tile key={s} status={s} counts={review.counts[s]} />
      ))}
    </div>
  );
}
