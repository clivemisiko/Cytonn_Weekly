"use client";

import { useSyncExternalStore } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/review/banners";
import { Masthead } from "@/components/review/masthead";
import { SSO_ENABLED } from "@/lib/sso";

const EASE = [0.23, 1, 0.32, 1] as const;
// Six blocks, 60ms apart, 320ms each: the last one lands at 620ms.
const STAGGER = 0.06;
const DURATION = 0.32;

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

const subscribe = () => () => {};
const clientGreeting = () => greetingFor(new Date().getHours());
const serverGreeting = () => null;

/**
 * The greeting by the viewer's own clock. The server cannot know that clock, so the server render and the first
 * client render both have none (null), and it appears once the page is live in the browser: never a wrong greeting.
 */
function useGreeting(): string | null {
  return useSyncExternalStore(subscribe, clientGreeting, serverGreeting);
}

/** One block of the page, rising into place in its turn. With reduced motion it is simply there. */
function Rise({ order, reduced, className, children }: { order: number; reduced: boolean; className?: string; children: React.ReactNode }) {
  return (
    <motion.div
      data-rise
      className={className}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduced ? { duration: 0 } : { duration: DURATION, ease: EASE, delay: order * STAGGER }}
    >
      {children}
    </motion.div>
  );
}

/**
 * The first screen: what the tool is, that it is ready, and the way in. Sign-in with Cytonn SSO is not built
 * (lib/sso.ts, api/sso.py), so its button is disabled and says so, and the page states plainly that nothing here is
 * protected. `displayName` is for the signed-in name once sign-in exists; nothing passes it today.
 */
export function LandingPage({ displayName }: { displayName?: string }) {
  const greeting = useGreeting();
  const reduced = useReducedMotion() ?? false;
  const hello = greeting ? (displayName ? `${greeting}, ${displayName}. ` : `${greeting}. `) : "";

  return (
    <main id="main" tabIndex={-1}>
      {/* Without scripts the blocks would stay at their starting opacity, so show them as they are. */}
      <noscript>
        <style>{"[data-rise]{opacity:1!important;transform:none!important}"}</style>
      </noscript>
      <Masthead title="Draft generator" />
      <div className="mx-auto w-full max-w-xl px-4 pt-8 pb-16 sm:px-6 sm:pt-16">
        <div className="space-y-6">
          <Rise order={0} reduced={reduced}>
            <h2 className="text-xl font-semibold sm:text-2xl">{hello}Welcome to Cytonn Weekly.</h2>
          </Rise>

          <Rise order={1} reduced={reduced}>
            <p className="max-w-[60ch] text-base text-muted-foreground">
              Your drafting assistant for the weekly report. It gathers the figures, drafts each section, and checks every figure
              against its source before a person approves anything.
            </p>
          </Rise>

          <Rise order={2} reduced={reduced}>
            <p role="status" className="flex items-center gap-3 text-sm font-medium">
              <span className="ready-dot" aria-hidden />
              Ready. Nothing is drafted until you ask.
            </p>
          </Rise>

          <Rise order={3} reduced={reduced} className="space-y-2 border-t pt-6">
            <Button size="lg" className="w-full sm:w-auto" disabled={!SSO_ENABLED} aria-describedby={SSO_ENABLED ? undefined : "sso-state"}>
              Sign in with Cytonn SSO
            </Button>
            {!SSO_ENABLED && (
              <p id="sso-state" className="text-xs text-muted-foreground">
                Not connected yet.
              </p>
            )}
          </Rise>

          <Rise order={4} reduced={reduced}>
            <Button asChild size="lg" variant="outline" className="w-full sm:w-auto">
              <Link href="/overview">Continue without signing in</Link>
            </Button>
          </Rise>

          <Rise order={5} reduced={reduced}>
            <Notice tone="info">
              Sign-in with Cytonn SSO is not connected yet. Until it is, this tool has no sign-in and should only be used by the
              team. Draft output is a first version for human review.
            </Notice>
          </Rise>
        </div>
      </div>
    </main>
  );
}
