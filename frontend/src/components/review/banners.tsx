"use client";

import { motion } from "motion/react";
import { InfoIcon, LockSimpleIcon, WarningCircleIcon, WarningIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { friendlyTime } from "@/lib/format";
import type { Decision } from "@/lib/types";

const TONES = {
  flag: { box: "border-flag/40 bg-flag/10 text-flag-fg", Icon: WarningCircleIcon },
  warn: { box: "border-warn/40 bg-warn/10 text-warn-fg", Icon: WarningIcon },
  info: { box: "border-border bg-muted text-foreground", Icon: InfoIcon },
} as const;

/** One alert box for the whole app: flag for errors, warn for cautions, info for plain notes. */
export function Notice({
  tone = "flag",
  role,
  className,
  children,
}: {
  tone?: keyof typeof TONES;
  role?: "alert" | "status";
  className?: string;
  children: React.ReactNode;
}) {
  const { box, Icon } = TONES[tone];
  return (
    <div role={role} className={cn("flex items-start gap-2 rounded-lg border px-3 py-2 text-sm", box, className)}>
      <Icon weight="bold" className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span className="min-w-0">{children}</span>
    </div>
  );
}

/** Fixed ribbon: a local-model draft can never be mistaken for a production one. */
export function DevRibbon({ label }: { label: string }) {
  return (
    <div
      role="status"
      className="hatch-dev fixed inset-x-0 top-0 z-40 flex h-7 items-center justify-center border-b border-[#b07d0f] px-4 font-mono text-xs font-semibold tracking-[0.06em] text-[#2a0a07]"
    >
      <span className="truncate">{label}</span>
    </div>
  );
}

/** Persistent in-content alert for the same condition; the ribbon is chrome, this is part of the draft. */
export function DevAlert({ label }: { label: string }) {
  return (
    <Notice role="alert" className="font-semibold">
      {label}
    </Notice>
  );
}

export function LockBar({ decision, decidedAt }: { decision: Decision; decidedAt: string | null }) {
  const approved = decision === "approved";
  return (
    <motion.div
      role="status"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.23, 1, 0.32, 1] }}
      className={cn(
        "flex flex-col gap-1 rounded-lg border border-l-[6px] px-4 py-3",
        approved ? "border-ok/40 border-l-ok bg-ok/10" : "border-flag/40 border-l-flag bg-flag/10",
      )}
    >
      <span className={cn("flex items-center gap-2 text-base font-semibold", approved ? "text-ok-fg" : "text-flag-fg")}>
        <LockSimpleIcon weight="bold" className="size-4" aria-hidden />
        {approved ? "Approved" : "Rejected"} and locked
      </span>
      <span className="text-sm text-muted-foreground">
        Decision recorded{decidedAt ? ` on ${friendlyTime(decidedAt)}` : ""}. Every value below is frozen as drafted; nothing on
        this screen can be changed.
      </span>
    </motion.div>
  );
}
