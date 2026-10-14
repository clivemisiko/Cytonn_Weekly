"use client";

import { useEffect, useSyncExternalStore } from "react";

/** The start screen: where Home always goes, and where Back goes when a page names nowhere better. */
export const HOME = "/";

/**
 * Where the top bar's Back button goes from the page on screen. Each page says so itself (useBack), because most of
 * the app's screens are states of one page (overview, a section's start screen, an open review), not addresses the
 * browser's history knows. So Back never leaves the app, and a page opened from a link in a new tab still has one.
 *
 * - `none`: the start screen. Back is shown, disabled.
 * - `home`: no page of its own to go back to, so Back goes Home. This is also what a page that says nothing gets.
 * - `go` / `href`: the page's own parent (an open review's list of sections, say), named for the button's label.
 */
export type BackTarget =
  | { kind: "none" }
  | { kind: "home" }
  | { kind: "go"; to: string; go: () => void }
  | { kind: "href"; to: string; href: string };

export const BACK_HOME: BackTarget = { kind: "home" };
export const BACK_NONE: BackTarget = { kind: "none" };

let back: BackTarget = BACK_HOME;
// Asked before Home or Back leaves the page: the question to put, or null when nothing would be lost.
let leaveQuestion: string | null = null;
const listeners = new Set<() => void>();

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const setBack = (next: BackTarget) => {
  back = next;
  listeners.forEach((listener) => listener());
};

/** The page on screen tells the top bar where Back goes. Pass a stable value (a constant, or one from useMemo). */
export function useBack(target: BackTarget): void {
  useEffect(() => {
    setBack(target);
    return () => setBack(BACK_HOME);
  }, [target]);
}

/** What the top bar's Back button does now. */
export function useBackTarget(): BackTarget {
  return useSyncExternalStore(
    subscribe,
    () => back,
    () => BACK_HOME,
  );
}

/** While `unsaved` is true, Home and Back ask `question` first and stay on the page unless the answer is yes. */
export function useLeaveGuard(unsaved: boolean, question: string): void {
  useEffect(() => {
    if (!unsaved) return;
    leaveQuestion = question;
    return () => {
      leaveQuestion = null;
    };
  }, [unsaved, question]);
}

/** True if the page may be left: nothing is unsaved, or the person said to leave anyway. */
export function mayLeave(): boolean {
  // ponytail: the browser's own confirm box; swap for the app's Dialog if the wording or styling needs to match.
  return leaveQuestion === null || window.confirm(leaveQuestion);
}
