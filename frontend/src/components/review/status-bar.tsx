"use client";

import { AnimatePresence, motion } from "motion/react";
import { CheckCircleIcon, InfoIcon, WarningIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import type { Decision, Review } from "@/lib/types";
import { Notice } from "./banners";
import { DecisionControls } from "./decision-controls";

const EASE = [0.23, 1, 0.32, 1] as const;

function Message({ review }: { review: Review }) {
  const { progress } = review;
  if (review.decision) {
    return (
      <span className="flex items-center gap-2 text-foreground">
        <InfoIcon weight="bold" className="size-4 shrink-0 text-link" aria-hidden />
        <span>
          Decision recorded: <strong className="font-semibold">{review.decision}</strong>.
        </span>
      </span>
    );
  }
  if (review.is_approvable) {
    return (
      <span className="flex items-center gap-2 text-ok-fg">
        <CheckCircleIcon weight="bold" className="size-4 shrink-0" aria-hidden />
        <span>Approvable: every item is resolved and none needs a fix.</span>
      </span>
    );
  }
  // The unresolved count is the bar's headline, so this line says only what still stands in the way.
  return (
    <span className="flex items-center gap-2 text-warn-fg">
      <WarningIcon weight="bold" className="size-4 shrink-0" aria-hidden />
      <span>
        {progress.fix_needed
          ? `Not approvable yet: ${progress.fix_needed} marked fix needed.`
          : "Approve unlocks once every item is resolved and none needs a fix."}
      </span>
    </span>
  );
}

/**
 * Sticky under the masthead for the whole review: how many items are left, whether the section can be approved,
 * and the decision itself, so the coordinator never has to scroll to the end of a long section to find either.
 */
export function StatusBar({
  review,
  saving,
  saveError,
  hasDevRibbon,
  deciding,
  decisionError,
  onDecide,
  onClose,
}: {
  review: Review;
  saving: boolean;
  saveError: string | null;
  hasDevRibbon: boolean;
  deciding: boolean;
  decisionError: string | null;
  onDecide: (decision: Decision) => Promise<boolean>;
  onClose: () => void;
}) {
  const { progress } = review;
  const fraction = progress.total ? progress.resolved / progress.total : 0;
  const messageKey = review.decision ? "decided" : review.is_approvable ? "ok" : "open";
  return (
    <div
      className={cn(
        "sticky z-30 -mx-4 border-b bg-background/95 px-4 py-3 backdrop-blur supports-backdrop-filter:bg-background/85 sm:-mx-6 sm:px-6",
        hasDevRibbon ? "top-7" : "top-0",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div className="min-w-55 flex-1 sm:max-w-sm">
          <div className="mb-2 flex items-baseline justify-between gap-3 text-sm">
            <span>
              <span className="font-semibold">
                <span className="font-mono">{progress.unresolved}</span> unresolved
              </span>
              <span className="text-muted-foreground">
                {" "}
                · <span className="font-mono">{progress.resolved}</span> of <span className="font-mono">{progress.total}</span> resolved
              </span>
            </span>
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {saving ? "Saving…" : saveError ? "Not saved" : `Saved as run ${review.run_id}`}
            </span>
          </div>
          <div
            role="progressbar"
            aria-label="Items resolved"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.resolved}
            className="h-2 overflow-hidden rounded-full bg-border"
          >
            <motion.div
              className="h-full origin-left rounded-full bg-primary"
              initial={false}
              animate={{ scaleX: fraction }}
              transition={{ duration: 0.24, ease: EASE }}
            />
          </div>
        </div>
        <div className="relative min-h-6 basis-full text-sm font-medium sm:flex-1 sm:basis-0" aria-live="polite">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={messageKey}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4, transition: { duration: 0.1 } }}
              transition={{ duration: 0.16, ease: EASE }}
            >
              <Message review={review} />
            </motion.div>
          </AnimatePresence>
        </div>
        <div className="basis-full lg:basis-auto">
          <DecisionControls review={review} deciding={deciding} onDecide={onDecide} onClose={onClose} />
        </div>
      </div>
      <AnimatePresence initial={false}>
        {decisionError && (
          <motion.div
            key="decision-error"
            role="alert"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="overflow-hidden"
          >
            <Notice className="mt-3 font-medium">{decisionError}</Notice>
          </motion.div>
        )}
        {saveError && (
          <motion.div
            key="save-error"
            role="alert"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="overflow-hidden"
          >
            <Notice className="mt-3 font-medium">
              NOT SAVED: {saveError}. The last change did not reach the server; the screen shows what the server holds.
            </Notice>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
