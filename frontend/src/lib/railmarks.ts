import { PhCheckCircle, PhCircle, PhCircleDashed, PhCircleHalf, PhCircleNotch, PhHourglass, PhLockSimple, PhWarningCircle } from "@phosphor-icons/vue";
import type { RailState } from "./shell";

export const MARKS: Record<RailState | "unknown", { label: string; icon: typeof PhCircle; tone: string }> = {
  approved: { label: "Approved", icon: PhCheckCircle, tone: "text-ok-fg" },
  rejected: { label: "Rejected", icon: PhWarningCircle, tone: "text-flag-fg" },
  in_review: { label: "In review", icon: PhCircleHalf, tone: "text-foreground" },
  not_drafted: { label: "Not drafted", icon: PhCircle, tone: "text-muted-foreground" },
  unavailable: { label: "Not available yet", icon: PhLockSimple, tone: "text-muted-foreground" },
  drafting: { label: "Being drafted", icon: PhCircleNotch, tone: "text-foreground" },
  queued: { label: "Queued", icon: PhHourglass, tone: "text-muted-foreground" },
  unknown: { label: "State not known", icon: PhCircleDashed, tone: "text-muted-foreground" },
};
