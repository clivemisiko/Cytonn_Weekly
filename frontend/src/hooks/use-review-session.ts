"use client";

import { useCallback, useRef, useState } from "react";
import * as api from "@/lib/api";
import type { Decision, Resolution, Review } from "@/lib/types";

const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err));

/**
 * One open review, kept in step with the server.
 *
 * Every write goes through one queue, so writes reach the API in the order they were made (the API
 * rewrites the whole items list per write, and two quick clicks must not overtake each other), and
 * every response is the full review as of that write.  The screen therefore always shows what the
 * server holds; a failed write is reported loudly and the screen is re-synced from the server.
 */
export function useReviewSession(initial: Review) {
  const runId = initial.run_id;
  const [review, setReview] = useState(initial);
  const [inFlight, setInFlight] = useState(0);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const tail = useRef<Promise<unknown>>(Promise.resolve());

  const send = useCallback(
    (call: () => Promise<Review>): Promise<boolean> => {
      setInFlight((n) => n + 1);
      const task = tail.current.then(async () => {
        try {
          setReview(await call());
          setSaveError(null);
          return true;
        } catch (err) {
          setSaveError(messageOf(err));
          try {
            setReview(await api.getReview(runId)); // never leave a failed write on screen as if it had saved
          } catch {
            /* the API is unreachable: keep what is shown, the banner says it was not saved */
          }
          return false;
        } finally {
          setInFlight((n) => n - 1);
        }
      });
      tail.current = task;
      return task;
    },
    [runId],
  );

  const resolve = useCallback(
    (index: number, resolution: Resolution, note?: string) => send(() => api.resolveItem(runId, index, resolution, note)),
    [runId, send],
  );

  const acceptClean = useCallback(() => send(() => api.acceptClean(runId)), [runId, send]);

  const decide = useCallback(
    async (decision: Decision): Promise<boolean> => {
      setDeciding(true);
      setDecisionError(null);
      try {
        await tail.current; // let any in-flight resolution land first, so approvability is judged on it
        setReview(await api.decide(runId, decision));
        return true;
      } catch (err) {
        setDecisionError(messageOf(err));
        try {
          setReview(await api.getReview(runId)); // e.g. approvability changed, or it was decided elsewhere
        } catch {
          /* keep what is shown */
        }
        return false;
      } finally {
        setDeciding(false);
      }
    },
    [runId],
  );

  return {
    review,
    saving: inFlight > 0,
    saveError,
    decisionError,
    deciding,
    resolve,
    acceptClean,
    decide,
  };
}
