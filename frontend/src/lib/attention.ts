import { nextTick, shallowRef } from "vue";
import type { ApiProblem } from "./api";

/**
 * What the screen does when an action fails with a named problem (the `problems` an API error carries, from
 * backend/api/problems.py). Each code has one placement:
 *
 * - `dialog`: the whole action failed. An alert dialog names it ("Show me" and "Close") and the full sentence stays on
 *   the page, once.
 * - `inline`: the sentence is on the page beside what was clicked; the page goes to it (scroll only if it is out of
 *   view, then focus), with no dialog.
 * - `none`: the page is itself the message (a review or run that no longer exists); nothing more is done.
 *
 * A Vitest compares these 30 codes with the backend's, so a code added on one side only fails the suite.
 */
export const PLACEMENT = {
  upload_refused: "inline",
  upload_too_big: "inline",
  note_refused: "inline",
  week_not_valid: "inline",
  analyst_refused: "inline",
  analyst_nothing_to_carry: "inline",
  analyst_suggestion_unavailable: "inline",
  bulletin_not_published: "inline",
  bulletin_fetch_failed: "inline",
  draft_section_unavailable: "dialog",
  draft_topic_missing: "inline",
  draft_topic_invalid: "inline",
  draft_text_missing: "inline",
  drafting_off: "dialog",
  draft_busy: "dialog",
  draft_already_running: "dialog",
  draft_mode_changed: "dialog",
  draft_discarded: "dialog",
  draft_sections_not_approved: "dialog",
  draft_input_invalid: "inline",
  draft_failed: "dialog",
  review_already_decided: "dialog",
  review_not_decidable: "dialog",
  review_not_found: "none",
  run_unknown: "none",
  export_not_ready: "dialog",
  fix_not_possible: "dialog",
  fix_file_refused: "dialog",
  fix_file_too_big: "dialog",
  fix_check_failed: "dialog",
} as const satisfies Record<string, "dialog" | "inline" | "none">;

export type ProblemCode = keyof typeof PLACEMENT;
export type Placement = (typeof PLACEMENT)[ProblemCode];

/** The parts of the page a problem can point at: each is an element carrying `data-attention="<target>"`. */
export const TARGETS = ["inputs-panel", "week-picker", "analyst-form", "start-draft", "review-status-bar", "export-bar"] as const;

/** A code the frontend does not know (a newer backend) is left alone, as a problem with no placement. */
export const placementOf = (code: string): Placement => (code in PLACEMENT ? PLACEMENT[code as ProblemCode] : "none");

/** The problem the page should act on: the first one with a placement, or null. */
export function firstActionable(problems: ApiProblem[]): ApiProblem | null {
  return problems.find((p) => placementOf(p.code) !== "none") ?? null;
}

/** True when the box is not wholly in the visible band between `topInset` (the sticky bars) and the viewport's foot. */
export function needsScroll(rect: { top: number; bottom: number }, viewportHeight: number, topInset: number): boolean {
  return rect.top < topInset || rect.bottom > viewportHeight;
}

/** The dialog on screen: one problem, replaced (never stacked) when another arrives. */
export const dialogProblem = shallowRef<ApiProblem | null>(null);

/** The attribute that marks a problem the page has gone to (styles.css draws its outline and pulse). */
export const HIGHLIGHT = "data-attention-on";

/** Mark a problem as the one the page went to. Set again on an element that already has it, so its pulse runs again. */
export function highlight(el: Pick<HTMLElement, "removeAttribute" | "setAttribute" | "offsetWidth">): void {
  el.removeAttribute(HIGHLIGHT);
  void el.offsetWidth; // a reflow between the two, or the browser does not restart the animation
  el.setAttribute(HIGHLIGHT, "");
}

const frame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

function targetOf(target: string | null): HTMLElement | null {
  if (!target || typeof document === "undefined") return null;
  return document.querySelector<HTMLElement>(`[data-attention="${target}"]`);
}

/** Whether "Show me" has somewhere to go: the target is on the page and has a box (a folded panel has none). */
export function canShow(problem: ApiProblem | null): boolean {
  const el = targetOf(problem?.target ?? null);
  return !!el && el.getClientRects().length > 0;
}

function editing(): boolean {
  const el = document.activeElement as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

/**
 * Go to a problem's place: after two frames (so the component has drawn the error), scroll its first `[data-problem]`
 * (else the target itself) into view only if it is out of view (at once under reduced motion), mark it (`highlight`), then
 * focus it. Focus is
 * never moved out of a field the person is typing in (a failed save on blur is noticed when they look up).
 * Returns false when the target is not on the page.
 */
export async function goTo(target: string | null, { force = false } = {}): Promise<boolean> {
  await nextTick();
  await frame();
  await frame();
  const el = targetOf(target);
  if (!el || el.getClientRects().length === 0) return false;
  // The problem itself is what must be seen (a tall panel can be half in view with its error out of it).
  const problem = el.querySelector<HTMLElement>("[data-problem]");
  const focusable = problem ?? el;
  if (problem) highlight(problem);
  const inset = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
  if (needsScroll(focusable.getBoundingClientRect(), window.innerHeight, inset)) {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    focusable.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
  }
  if (!force && editing()) return true;
  if (!focusable.hasAttribute("tabindex")) focusable.setAttribute("tabindex", "-1");
  focusable.focus({ preventScroll: true });
  return true;
}

/**
 * An action failed with these problems (installed as the API's failure handler in main.ts, so it is called for
 * failed writes only, never for reads). A dialog problem opens the dialog, replacing any already open; an inline one
 * goes to its place; `none` does nothing.
 */
export function raise(problems: ApiProblem[]): void {
  const problem = firstActionable(problems);
  if (!problem) return;
  if (placementOf(problem.code) === "dialog") dialogProblem.value = problem;
  else void goTo(problem.target);
}

/** Close the dialog. */
export function dismiss(): void {
  dialogProblem.value = null;
}
