import { shallowRef } from "vue";
import type { SentenceResult } from "./types";

/** The most characters a hand-typed sentence may have; the API judges it the same way (weekly/sentence_edit.py). */
export const MAX_SENTENCE = 600;

/** The most characters a hand-typed carried-forward paragraph may have; the API judges it the same way. */
export const MAX_PARAGRAPH = 1200;

/** The most characters Real Estate's standing REITs text may have (a paragraph and its list, a line each); the API judges it the same way. */
export const MAX_STANDING = 4000;

/** What the API stores for the standing text: each line tidied, empty lines dropped, the lines kept. */
const standingLines = (text: string): string => text.split(/\r?\n/).map(tidy).filter(Boolean).join("\n");

/** Like sentenceCheck for the standing text, where each line stays a line. */
export function standingCheck(text: string, original: string): SentenceCheck {
  const stored = standingLines(text);
  const length = [...stored].length;
  const over = Math.max(0, length - MAX_STANDING);
  return { length, over, empty: length === 0, same: stored === standingLines(original), ok: length > 0 && over === 0 && stored !== standingLines(original) };
}

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

export const REMOVE_FINDING_NOTE =
  "The whole finding, with its sources, will not appear in the review or the Word export. Only a new draft of this section brings it back. The current version stays saved.";

/** The result of the latest sentence change, with the new review's run id, so the review it opened can show it. */
export const lastSentence = shallowRef<{ runId: number; result: SentenceResult } | null>(null);
