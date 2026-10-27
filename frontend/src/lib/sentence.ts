import { shallowRef } from "vue";
import type { SentenceResult } from "./types";

/** The most characters a hand-typed sentence may have; the API judges it the same way (weekly/sentence_edit.py). */
export const MAX_SENTENCE = 600;

/** The most characters a hand-typed carried-forward paragraph may have; the API judges it the same way. */
export const MAX_PARAGRAPH = 1200;

/** What the API stores: one line, single spaces. */
export const tidy = (text: string): string => text.split(/\s+/).filter(Boolean).join(" ");

/** The counted length, in characters as a person sees them, of what would be stored. */
export const sentenceLength = (text: string): number => [...tidy(text)].length;

export interface SentenceCheck {
  length: number;
  over: number;
  empty: boolean;
  same: boolean;
  ok: boolean;
}

/** Whether the typed sentence can be saved. Which characters are allowed is the API's to say; only length, empty and unchanged are judged here. */
export function sentenceCheck(text: string, original: string, limit: number = MAX_SENTENCE): SentenceCheck {
  const length = sentenceLength(text);
  const over = Math.max(0, length - limit);
  const empty = length === 0;
  const same = tidy(text) === tidy(original);
  return { length, over, empty, same, ok: !empty && over === 0 && !same };
}

export const APPROVED_SENTENCE_NOTE =
  "This section is approved. Saving creates a new version and removes the approval: the new version needs approving again. The approved version stays saved.";

/** The result of the latest sentence change, with the new review's run id, so the review it opened can show it. */
export const lastSentence = shallowRef<{ runId: number; result: SentenceResult } | null>(null);
