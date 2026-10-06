"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Decision, Review } from "@/lib/types";

const EASE = [0.23, 1, 0.32, 1] as const;

const COPY: Record<Decision, { title: string; body: string; confirm: string }> = {
  approved: {
    title: "Approve this section?",
    body: "Every value is accepted as drafted. This is recorded once and cannot be changed.",
    confirm: "Approve",
  },
  rejected: {
    title: "Reject this section?",
    body: "The draft is sent back and frozen as it is. This is recorded once and cannot be changed; a new draft would have to be run.",
    confirm: "Reject",
  },
};

/**
 * The section's one decision, as it sits in the sticky status bar: Approve, Reject and the warning that the
 * decision is final, or (once decided) the way back; the status bar's message states the outcome. Each choice is confirmed in a dialog.
 */
export function DecisionControls({
  review,
  deciding,
  onDecide,
  onClose,
}: {
  review: Review;
  deciding: boolean;
  onDecide: (decision: Decision) => Promise<boolean>;
  onClose: () => void;
}) {
  const [asking, setAsking] = useState<Decision | null>(null);
  const decided = review.decision !== null;
  const canApprove = review.is_approvable && !decided;

  const confirm = async () => {
    if (!asking) return;
    await onDecide(asking);
    setAsking(null);
  };

  return (
    <div role="group" aria-label="Decision">
      <AnimatePresence mode="wait" initial={false}>
        {decided ? (
          <motion.div
            key="decided"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.16, ease: EASE }}
            className="flex flex-wrap items-center gap-3 lg:justify-end"
          >
            <Button variant="outline" onClick={onClose}>
              Back to all sections
            </Button>
          </motion.div>
        ) : (
          <motion.div
            key="open"
            exit={{ opacity: 0, transition: { duration: 0.1 } }}
            className="flex items-center gap-x-4 lg:justify-end"
          >
            <p className="order-last max-w-64 min-w-0 text-xs text-muted-foreground lg:order-first lg:text-right">
              <span className="hidden lg:inline">One decision for the whole section. </span>Once recorded, it cannot be changed.
            </p>
            <div className="flex items-center gap-3">
              <Button size="lg" disabled={!canApprove || deciding} onClick={() => setAsking("approved")}>
                Approve
              </Button>
              <Button size="lg" variant="outline" disabled={deciding} onClick={() => setAsking("rejected")}>
                Reject
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Dialog open={asking !== null} onOpenChange={(o) => !o && !deciding && setAsking(null)}>
        <DialogContent showCloseButton={false} className="sm:max-w-md">
          {asking && (
            <>
              <DialogHeader>
                <DialogTitle>{COPY[asking].title}</DialogTitle>
                <DialogDescription>{COPY[asking].body}</DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" disabled={deciding} onClick={() => setAsking(null)}>
                  Cancel
                </Button>
                <Button disabled={deciding} onClick={() => void confirm()} variant={asking === "rejected" ? "destructive" : "default"}>
                  {deciding ? "Recording…" : COPY[asking].confirm}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
