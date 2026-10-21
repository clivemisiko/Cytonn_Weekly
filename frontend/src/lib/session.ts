import { computed, ref, shallowRef } from "vue";
import * as api from "./api";
import type { Decision, Resolution, Review } from "./types";

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
  const review = shallowRef(initial);
  const inFlight = ref(0);
  const saveError = ref<string | null>(null);
  const decisionError = ref<string | null>(null);
  const deciding = ref(false);
  let tail: Promise<unknown> = Promise.resolve();

  function send(call: () => Promise<Review>): Promise<boolean> {
    inFlight.value++;
    const task = tail.then(async () => {
      try {
        review.value = await call();
        saveError.value = null;
        return true;
      } catch (err) {
        saveError.value = messageOf(err);
        try {
          review.value = await api.getReview(runId); // never leave a failed write on screen as if it had saved
        } catch {
          /* the API is unreachable: keep what is shown, the banner says it was not saved */
        }
        return false;
      } finally {
        inFlight.value--;
      }
    });
    tail = task;
    return task;
  }

  const resolve = (index: number, resolution: Resolution, note?: string) => send(() => api.resolveItem(runId, index, resolution, note));
  const acceptClean = () => send(() => api.acceptClean(runId));
  const setTeamChart = (chartId: string, use: boolean) => send(() => api.setTeamChart(runId, chartId, use));

  async function decide(decision: Decision): Promise<boolean> {
    deciding.value = true;
    decisionError.value = null;
    try {
      await tail; // let any in-flight resolution land first, so approvability is judged on it
      review.value = await api.decide(runId, decision);
      return true;
    } catch (err) {
      decisionError.value = messageOf(err);
      try {
        review.value = await api.getReview(runId); // e.g. approvability changed, or it was decided elsewhere
      } catch {
        /* keep what is shown */
      }
      return false;
    } finally {
      deciding.value = false;
    }
  }

  return { review, saving: computed(() => inFlight.value > 0), saveError, decisionError, deciding, resolve, acceptClean, setTeamChart, decide };
}
