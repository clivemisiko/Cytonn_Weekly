import { shallowRef, type InjectionKey } from "vue";
import * as api from "./api";
import type { FixResult, InputSlot, Review } from "./types";

/**
 * "Fix from the item": what the screen remembers between the card that uploaded a file and the new review that opens.
 * Nothing here works anything out; the figures, the old and new values and the kept parts all come from the API.
 */

/** The result of the latest re-check, with the new review's run id, so the review it opened can show it. */
export const lastRecheck = shallowRef<{ runId: number; result: FixResult } | null>(null);

/** Given by the review screen: show another review (the new version) in its place. */
export const OPEN_REVIEW: InjectionKey<(review: Review) => void> = Symbol("open-rechecked-review");

// Which inputs a week already holds, read once per week for all the cards ("Add the missing file" or "Replace the file").
const known = new Map<string, Promise<InputSlot[]>>();

export function slotsFor(week: string): Promise<InputSlot[]> {
  let found = known.get(week);
  if (!found) {
    found = api.getInputs(week).then((s) => s.slots);
    found.catch(() => known.delete(week)); // a failed read is tried again next time
    known.set(week, found);
  }
  return found;
}

/** An upload changed what the week holds. */
export const forgetSlots = (week: string) => known.delete(week);

export const APPROVED_NOTE = "This section is approved. Checking the new file creates a new version that needs approving again.";

/** One change as a sentence: old figure, then new figure. */
export const changeLine = (c: FixResult["changes"][number]) => `${c.block}: ${c.label}: was ${c.old}, now ${c.new}.`;

/** The names of what was left as it was, shortened to the first few. */
export function keptNames(kept: string[], show = 6): string {
  const names = [...new Set(kept)];
  return names.length <= show ? names.join(", ") : `${names.slice(0, show).join(", ")} and ${names.length - show} more`;
}
