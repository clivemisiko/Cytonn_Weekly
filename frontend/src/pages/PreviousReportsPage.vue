<script setup lang="ts">
import { PhCheckCircle, PhWarning } from "@phosphor-icons/vue";
import { computed, onUnmounted, shallowRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import PageGrid from "@/components/nav/PageGrid.vue";
import Masthead from "@/components/review/Masthead.vue";
import Notice from "@/components/review/Notice.vue";
import OverviewSkeleton from "@/components/review/OverviewSkeleton.vue";
import ReviewScreen from "@/components/review/ReviewScreen.vue";
import ReviewSkeleton from "@/components/review/ReviewSkeleton.vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { friendlyDate } from "@/lib/format";
import { BACK_HOME, type BackTarget, useBack } from "@/lib/nav";
import { NO_WEEKS, weekRow } from "@/lib/previous";
import { shell } from "@/lib/shell";
import type { ExportStatus, PreviousWeek, Review } from "@/lib/types";

type Phase =
  | { name: "loading"; target: "list" | "review" }
  | { name: "error"; message: string }
  | { name: "list"; weeks: PreviousWeek[] }
  | { name: "week"; status: ExportStatus; week: PreviousWeek | null }
  | { name: "review"; review: Review };

const route = useRoute();
const router = useRouter();
const phase = shallowRef<Phase>({ name: "loading", target: "list" });
const downloading = shallowRef<string | null>(null);
const downloadError = shallowRef<string | null>(null);
let live = true;
onUnmounted(() => (live = false));
shell.invalidate(); // this page hands the rail no report, so no section's state is shown as known

const one = (v: unknown) => (Array.isArray(v) ? v[0] : v) as string | undefined;
const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** The list (no query), one week's five sections (?period=), or one of its reviews read only (?review=). */
async function load() {
  const reviewId = Number(one(route.query.review));
  const period = one(route.query.period);
  phase.value = { name: "loading", target: Number.isInteger(reviewId) && reviewId > 0 ? "review" : "list" };
  let next: Phase;
  try {
    if (Number.isInteger(reviewId) && reviewId > 0) {
      next = { name: "review", review: await api.getReview(reviewId) };
    } else if (period !== undefined) {
      const [status, all] = await Promise.all([api.getExportStatus(period), api.getPreviousWeeks()]);
      next = { name: "week", status, week: all.weeks.find((w) => w.period === status.period) ?? null };
    } else {
      next = { name: "list", weeks: (await api.getPreviousWeeks()).weeks };
    }
  } catch (err) {
    next = { name: "error", message: messageOf(err) };
  }
  if (live) phase.value = next;
}
watch(() => [route.query.review, route.query.period], load, { immediate: true });

const go = (query: Record<string, string>) => void router.push({ path: "/previous", query });
const openWeek = (period: string) => go({ period });
const openReview = (runId: number) => go({ review: String(runId) });

const LIST: BackTarget = { kind: "go", to: "Previous reports", go: () => go({}) };
useBack(() => {
  const p = phase.value;
  if (p.name === "review") return { kind: "go", to: "the week", go: () => openWeek(p.review.period) };
  if (p.name === "week") return LIST;
  return BACK_HOME;
});

async function download(period: string) {
  downloading.value = period;
  downloadError.value = null;
  try {
    const { blob, name } = await api.exportWeekly(period);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    downloadError.value = messageOf(err);
  } finally {
    downloading.value = null;
  }
}

const weekTitle = computed(() => {
  const p = phase.value;
  if (p.name !== "week") return "";
  return p.week ? weekRow(p.week).title : p.status.period || "Weekly report";
});
</script>

<template>
  <main id="main" tabindex="-1">
    <ReviewSkeleton v-if="phase.name === 'loading' && phase.target === 'review'" />
    <OverviewSkeleton v-else-if="phase.name === 'loading'" />

    <template v-else-if="phase.name === 'error'">
      <Masthead wide title="Previous reports" />
      <PageGrid>
        <div class="max-w-xl space-y-4">
          <Notice role="alert" class="font-medium">{{ phase.message }}</Notice>
          <Button size="lg" @click="load">Try again</Button>
        </div>
      </PageGrid>
    </template>

    <ReviewScreen v-else-if="phase.name === 'review'" :key="phase.review.run_id" :initial="phase.review" read-only @close="openWeek(phase.review.period)" />

    <template v-else>
      <Masthead wide :title="phase.name === 'week' ? `Previous reports: ${weekTitle}` : 'Previous reports'" />
      <PageGrid>
        <div class="space-y-4">
          <div v-if="downloadError" data-attention="export-bar">
            <Notice role="alert" data-problem class="font-medium">{{ downloadError }}</Notice>
          </div>

          <template v-if="phase.name === 'list'">
            <p class="text-sm text-muted-foreground">Weekly reports whose five sections are all approved, newest first. Each opens read only.</p>
            <div v-if="phase.weeks.length === 0" class="rounded-lg border bg-card p-6">
              <p class="text-sm">{{ NO_WEEKS }}</p>
            </div>
            <ul v-else class="space-y-3" aria-label="Approved weeks">
              <li v-for="w in phase.weeks" :key="w.period" class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-card p-4">
                <div class="min-w-0 flex-1 space-y-1">
                  <h2 class="text-base font-semibold">{{ weekRow(w).title }}</h2>
                  <p class="flex items-center gap-1.5 text-sm text-ok-fg">
                    <PhCheckCircle weight="bold" class="size-4 shrink-0" aria-hidden="true" />{{ weekRow(w).status }}
                  </p>
                  <p v-if="weekRow(w).approved" class="text-xs text-muted-foreground">{{ weekRow(w).approved }}</p>
                  <p v-if="weekRow(w).dev" class="flex items-center gap-1.5 text-xs font-semibold text-flag-fg">
                    <PhWarning weight="bold" class="size-4 shrink-0" aria-hidden="true" />{{ weekRow(w).dev }}
                  </p>
                </div>
                <div class="flex flex-wrap gap-2">
                  <Button variant="outline" :aria-label="`Read ${weekRow(w).title}`" @click="openWeek(w.period)">Read</Button>
                  <Button
                    :disabled="!w.can_export || downloading !== null"
                    :aria-label="`Download Word for ${weekRow(w).title}`"
                    @click="download(w.period)"
                  >
                    {{ downloading === w.period ? "Preparing…" : "Download Word" }}
                  </Button>
                </div>
              </li>
            </ul>
          </template>

          <template v-else-if="phase.name === 'week'">
            <Notice v-if="!phase.status.ready" role="alert" class="font-medium">
              This week's report is no longer marked as fully approved because one or more sections have newer drafts. Please visit the Overview to review pending changes.
            </Notice>
            <Notice v-if="phase.status.is_dev_draft" role="alert" class="font-semibold">
              {{ phase.status.dev_mode_label }}: The exported document contains a developer watermark on every page ({{ phase.status.dev_sections.join(", ") }}).
            </Notice>
            <p v-if="phase.week" class="text-sm text-muted-foreground">
              Week ending {{ friendlyDate(phase.week.week_ending) }}. Each section opens its approved review read only.
            </p>
            <ol class="space-y-2" aria-label="Sections">
              <li v-for="s in phase.status.sections" :key="s.slug" class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-card p-4">
                <span class="min-w-0 flex-1 text-sm font-semibold">{{ s.title }}</span>
                <span class="text-xs text-muted-foreground">{{ s.state === "approved" ? "Approved" : s.state.replace("_", " ") }}</span>
                <Button v-if="s.run_id !== null" variant="outline" size="sm" :aria-label="`Read ${s.title}`" @click="openReview(s.run_id)">Read</Button>
              </li>
            </ol>
            <Button :disabled="!phase.status.ready || downloading !== null" @click="download(phase.status.period)">
              {{ downloading === phase.status.period ? "Preparing…" : "Download Word" }}
            </Button>
          </template>
        </div>
      </PageGrid>
    </template>
  </main>
</template>
