"use client";

import { motion } from "motion/react";
import { RadioGroup as RadioGroupPrimitive } from "radix-ui";
import { cn } from "cn";
import { RESOLUTION_LABELS, resolutionKey } from "@/lib/format";
import type { Resolution } from "@/lib/types";

const OPTIONS = ["none", "accept", "fix_needed"] as const;

// Fill behind the selected option: neutral for "unresolved", the state colours for the other two.
const THUMB: Record<(typeof OPTIONS)[number], string> = {
  none: "bg-foreground/10",
  accept: "bg-ok",
  fix_needed: "bg-flag",
};
const SELECTED_TEXT: Record<(typeof OPTIONS)[number], string> = {
  none: "text-foreground",
  accept: "text-ok-on",
  fix_needed: "text-flag-on",
};

/**
 * Unresolved | Accept | Fix needed, as one segmented control (a radio group, so it keeps arrow-key
 * navigation and a single tab stop).  The selection fill slides between options (a shared layout
 * element, scoped per item); selection is shown by fill AND weight, never colour alone.
 */
export function ResolutionControl({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: Resolution;
  disabled: boolean;
  onChange: (next: Resolution) => void;
}) {
  const current = resolutionKey(value);
  return (
    <RadioGroupPrimitive.Root
      value={current}
      disabled={disabled}
      aria-label={`Resolution for ${label}`}
      onValueChange={(v) => onChange(v === "none" ? null : (v as Resolution))}
      className={cn(
        "relative inline-flex w-fit overflow-hidden rounded-md border border-input bg-card",
        // Locked: a muted frame, not a fade, so the recorded choice keeps its full contrast.
        disabled && "border-border bg-muted",
      )}
    >
      {OPTIONS.map((opt) => {
        const selected = current === opt;
        return (
          <RadioGroupPrimitive.Item
            key={opt}
            value={opt}
            className={cn(
              "relative h-8 px-3 text-sm transition-[color,background-color,transform] duration-150 ease-out outline-none",
              "not-first:border-l not-first:border-border focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
              "disabled:cursor-not-allowed",
              selected ? cn("font-semibold", SELECTED_TEXT[opt]) : "font-medium text-muted-foreground not-disabled:hover:bg-muted not-disabled:hover:text-foreground",
            )}
          >
            {selected && (
              <motion.span
                layoutId={`resolution-thumb-${id}`}
                aria-hidden
                className={cn("absolute inset-0", THUMB[opt])}
                transition={{ type: "spring", duration: 0.22, bounce: 0 }}
              />
            )}
            <span className="relative">{RESOLUTION_LABELS[opt]}</span>
          </RadioGroupPrimitive.Item>
        );
      })}
    </RadioGroupPrimitive.Root>
  );
}
