<script setup lang="ts">
import {
  PhCaretDown,
  PhCheckCircle,
  PhCircle,
  PhCircleDashed,
  PhCircleHalf,
  PhCircleNotch,
  PhLockSimple,
  PhSidebarSimple,
  PhSquaresFour,
  PhWarningCircle,
} from "@phosphor-icons/vue";
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from "reka-ui";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { LINK } from "@/components/ui/button";
import { reportName } from "@/lib/format";
import { mayLeave, useBackTarget } from "@/lib/nav";
import { type RailSection, type RailState, shell } from "@/lib/shell";

const router = useRouter();
const back = useBackTarget();
const open = ref(false); // the narrow strip expanded over the page
const groupOpen = ref(true);

const MARKS: Record<RailState | "unknown", { label: string; icon: typeof PhCircle; tone: string }> = {
  approved: { label: "Approved", icon: PhCheckCircle, tone: "text-ok-fg" },
  rejected: { label: "Rejected", icon: PhWarningCircle, tone: "text-flag-fg" },
  in_review: { label: "In review", icon: PhCircleHalf, tone: "text-foreground" },
  not_drafted: { label: "Not drafted", icon: PhCircle, tone: "text-muted-foreground" },
  unavailable: { label: "Not available yet", icon: PhLockSimple, tone: "text-muted-foreground" },
  drafting: { label: "Being drafted", icon: PhCircleNotch, tone: "text-foreground" },
  unknown: { label: "State not known", icon: PhCircleDashed, tone: "text-muted-foreground" },
};
const markOf = (s: RailSection) => MARKS[s.state ?? "unknown"];

// Labels show from 1366px, or while the narrow strip is expanded; otherwise they are read by a screen reader only.
const label = computed(() => (open.value ? "" : "sr-only min-[1366px]:not-sr-only"));
const fullOnly = computed(() => (open.value ? "" : "max-[1365px]:hidden"));

const here = shell.here;
const atOverview = computed(() => here.value?.view === "overview");
const hereSlug = computed(() => (here.value?.view === "section" ? here.value.slug : null));
const canOpen = (s: RailSection) => shell.opener.value !== null && s.slug !== hereSlug.value && s.state !== "unavailable";

function openSection(s: RailSection) {
  if (!canOpen(s) || !mayLeave()) return;
  open.value = false;
  shell.opener.value?.(s.slug);
}

function toOverview() {
  if (atOverview.value || !mayLeave()) return;
  open.value = false;
  if (shell.toOverview.value) shell.toOverview.value();
  else void router.push(back.value.kind === "href" ? back.value.href : "/overview");
}

/** Why a section's item does nothing, for its tooltip and screen-reader text; null when it opens the section. */
function whyInert(s: RailSection): string | null {
  if (s.slug === hereSlug.value) return "this section is on screen";
  if (s.state === "unavailable") return "not available yet";
  if (shell.opener.value === null) return "open the overview first";
  return null;
}

/** What a screen reader says for the item: the section, its state, and why it does nothing when it does not. It starts
 *  with the visible label, so the name contains what is on screen. */
const nameOf = (s: RailSection) => `${s.title}, ${markOf(s).label}${whyInert(s) ? `, ${whyInert(s)}` : ""}`;

const mode = computed(() => {
  const c = shell.config.value;
  return c ? (c.dev_mode ? "Dev mode · local model" : `Production · ${c.provider}`) : null;
});
const showProgress = computed(() => shell.held.value !== null && !atOverview.value);

// The current item is a pale blue pill (and bold, and aria-current); an item that does nothing is dimmed and has no hover.
const ITEM =
  "flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm outline-none transition-colors duration-150 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring aria-disabled:cursor-default aria-disabled:opacity-60 aria-disabled:hover:bg-transparent aria-[current=page]:bg-accent aria-[current=page]:font-semibold aria-[current=page]:text-accent-foreground aria-[current=page]:hover:bg-accent";
</script>

<template>
  <!-- The wrapper is what sticks (under the top bar and the ribbon) and what holds the strip's 56px in the layout; the nav
       fills it, and when the strip is expanded it is wider than the wrapper and lies over the page. -->
  <div
    class="sticky top-[calc(var(--topbar-h)+var(--ribbon-h,0rem))] h-[calc(100dvh-var(--topbar-h)-var(--ribbon-h,0rem))] w-14 shrink-0 max-md:hidden min-[1366px]:w-56"
    :class="open && 'z-40'"
  >
    <nav
      aria-label="Report sections"
      class="flex h-full w-14 flex-col gap-4 overflow-x-hidden overflow-y-auto border-r bg-card p-1.5 min-[1366px]:w-56 min-[1366px]:p-3"
      :class="open && 'max-[1365px]:w-56'"
      @keydown.esc="open = false"
    >
      <button
        type="button"
        class="grid size-10 place-items-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring min-[1366px]:hidden"
        :aria-expanded="open"
        :aria-label="open ? 'Collapse the rail' : 'Expand the rail'"
        :title="open ? 'Collapse the rail' : 'Expand the rail'"
        @click="open = !open"
      >
        <PhSidebarSimple weight="bold" class="size-5" aria-hidden="true" />
      </button>

      <div v-if="shell.report.value" class="space-y-1 rounded-xl border border-border/80 bg-background/80 p-3 shadow-2xs" :class="!open && 'hidden min-[1366px]:block'">
        <p class="eyebrow">Report</p>
        <p class="text-sm font-semibold tracking-tight text-foreground">{{ reportName(shell.report.value.title, shell.report.value.period) }}</p>
        <p v-if="mode" class="text-xs text-muted-foreground">{{ mode }}</p>
        <button v-if="hereSlug && shell.toOverview.value" type="button" :class="['text-xs', LINK]" @click="toOverview">Change report</button>
      </div>

      <ul class="space-y-1">
        <li>
          <button type="button" :class="ITEM" :aria-current="atOverview ? 'page' : undefined" @click="toOverview">
            <PhSquaresFour weight="bold" class="size-5 shrink-0" aria-hidden="true" />
            <span :class="label">Overview</span>
          </button>
        </li>
      </ul>

      <CollapsibleRoot v-model:open="groupOpen" class="space-y-1">
        <CollapsibleTrigger class="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
          <PhCaretDown weight="bold" class="size-3 shrink-0 text-muted-foreground transition-transform duration-200" :class="!groupOpen && '-rotate-90'" aria-hidden="true" />
          <span class="eyebrow" :class="label">Sections</span>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <p v-if="shell.sections.value.length === 0" class="px-2 py-1 text-xs text-muted-foreground" :class="fullOnly">
            Open the overview to list this report’s sections.
          </p>
          <ul v-else class="space-y-1">
            <li v-for="s in shell.sections.value" :key="s.slug">
              <button
                type="button"
                :class="ITEM"
                :aria-current="s.slug === hereSlug ? 'page' : undefined"
                :aria-disabled="canOpen(s) || s.slug === hereSlug ? undefined : true"
                :aria-label="nameOf(s)"
                :title="`${s.title}: ${markOf(s).label}`"
                @click="openSection(s)"
              >
                <component
                  :is="markOf(s).icon"
                  weight="bold"
                  class="size-5 shrink-0"
                  :class="[markOf(s).tone, s.state === 'drafting' && 'animate-spin motion-reduce:animate-none']"
                  aria-hidden="true"
                />
                <span :class="[label, 'min-w-0 truncate']">{{ s.title }}</span>
              </button>
            </li>
          </ul>
        </CollapsibleContent>
      </CollapsibleRoot>

      <div v-if="showProgress" class="mt-auto space-y-2 rounded-xl border border-border/80 bg-muted/40 p-2.5 shadow-2xs min-[1366px]:p-3">
        <p class="text-center font-mono text-xs font-semibold" :class="open ? 'hidden' : 'min-[1366px]:hidden'" aria-hidden="true">
          {{ shell.approved.value === null ? "?" : shell.approved.value }}/{{ shell.total.value }}
        </p>
        <div :class="open ? '' : 'sr-only min-[1366px]:not-sr-only'" class="space-y-2">
          <p class="text-sm font-semibold tracking-tight text-foreground">
            {{ shell.approved.value === null ? "Approved count not known" : `${shell.approved.value} of ${shell.total.value} sections approved` }}
          </p>
          <div
            v-if="shell.approved.value !== null"
            role="progressbar"
            aria-label="Sections approved"
            aria-valuemin="0"
            :aria-valuemax="shell.total.value ?? 0"
            :aria-valuenow="shell.approved.value"
            class="h-1.5 overflow-hidden rounded-full bg-border"
          >
            <div
              class="h-full rounded-full transition-all duration-300"
              :class="shell.approved.value === shell.total.value ? 'bg-ok-fg' : 'bg-foreground'"
              :style="{ width: `${shell.total.value ? (shell.approved.value / shell.total.value) * 100 : 0}%` }"
            />
          </div>
          <p v-if="shell.report.value?.type === 'weekly'" class="text-xs text-muted-foreground">
            {{
              shell.approved.value !== null && shell.approved.value === shell.total.value
                ? "Ready to export from the overview."
                : `Export unlocks when all ${shell.total.value ?? ""} are approved.`
            }}
          </p>
        </div>
      </div>
    </nav>
  </div>
</template>
