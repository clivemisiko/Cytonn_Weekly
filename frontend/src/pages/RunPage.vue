<script setup lang="ts">
import { PhCheck, PhCircleNotch, PhMinus } from "@phosphor-icons/vue";
import { cn } from "cn";
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, useTemplateRef, watch } from "vue";
import { RouterLink } from "vue-router";
import PageGrid from "@/components/nav/PageGrid.vue";
import CountTile from "@/components/review/CountTile.vue";
import Masthead from "@/components/review/Masthead.vue";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { LINK, buttonVariants } from "@/components/ui/button";
import * as api from "@/lib/api";
import { STATUS_ORDER, friendlyTime, reportName } from "@/lib/format";
import { type BackTarget, useBack } from "@/lib/nav";
import { isTerminal, mergeEvents, overviewHref, stepLines } from "@/lib/run";
import { shell, useShellRibbon } from "@/lib/shell";
import type { AppConfig, Run, RunEvent } from "@/lib/types";

const POLL_MS = 2_000;
/** How close to the foot of the page counts as "following along". */
const FOLLOW_PX = 96;
const MARK_WORD = { working: "In progress", done: "Done", skipped: "Skipped", failed: "Failed" } as const;
const BOX = "grid size-5 shrink-0 place-items-center rounded-full";

/**
 * How the events are arriving. `stream`: the EventSource is open. `poll`: it could not be opened, so the run is read
 * every two seconds instead. `lost`: it was open and dropped mid-run; the run is still read every two seconds, and
 * the notice stays until a read succeeds. None of them ever starts a run.
 */
type Feed = "connecting" | "stream" | "poll" | "lost";

/**
 * One draft run as it happens: the section and report at the top, a status line, the run's steps, and (when it
 * ends) the result. Every line is an event the pipeline reported (lib/run.ts holds the wording); nothing is timed,
 * estimated or filled in, so when nothing is happening nothing on this screen moves. The run is only ever read
 * here: no code path on this screen starts one or retries one.
 */
const props = defineProps<{ runId: string }>();

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const run = shallowRef<Run | null>(null);
const events = shallowRef<RunEvent[]>([]);
const missing = ref(false);
const feed = ref<Feed>("connecting");
const config = shallowRef<AppConfig | null>(null);
let live = true;
let source: EventSource | null = null;

// The rail knows no section's state until this run's report has been read (below): nothing from the screen before.
shell.invalidate();

const ended = computed(() => events.value.some(isTerminal));
// The saved review's id and dev mark come with the run itself, which is read once more after its last event.
const settled = computed(() => run.value !== null && run.value.status !== "running");

/** Read the run once. A 404 means the API no longer has it; any other failure leaves the screen as it is. */
async function read(): Promise<boolean> {
  try {
    const next = await api.getRun(props.runId);
    if (!live) return true;
    run.value = next;
    events.value = mergeEvents(events.value, next.events);
    return true;
  } catch (err) {
    if (live && (err as api.ApiError).status === 404) missing.value = true;
    return false;
  }
}

onMounted(async () => {
  // The drafting provider, for the DEV MODE ribbon while a development draft is still running.
  api.getConfig().then(
    (c) => {
      if (!live) return;
      config.value = c;
      shell.config.value = c;
    },
    () => {},
  );
  // First the run itself (who it is, what it has reported so far, or that it is gone), then its live stream.
  const ok = await read();
  if (!live) return;
  if (!ok) {
    feed.value = "lost"; // unreachable just now (a missing run stops everything below by itself)
    return;
  }
  let opened = false;
  source = new EventSource(api.runEventsUrl(props.runId));
  source.onopen = () => {
    opened = true;
    feed.value = "stream";
  };
  source.addEventListener("step", (message) => {
    const event = JSON.parse((message as MessageEvent<string>).data) as RunEvent;
    events.value = mergeEvents(events.value, [event]);
    if (isTerminal(event)) source?.close(); // the server closes too; do not let the browser reconnect
  });
  source.onerror = () => {
    // Never let EventSource reconnect by itself: read the run plainly instead, every two seconds.
    source?.close();
    feed.value = opened ? "lost" : "poll";
  };
});
onUnmounted(() => {
  live = false;
  source?.close();
});

// Plain reads: while the stream is not carrying the run, and once after its last event for the saved review.
const reading = computed(() => !missing.value && !settled.value && (feed.value === "poll" || feed.value === "lost" || ended.value));
watch(
  [reading, ended],
  ([isReading, hasEnded], _before, onCleanup) => {
    if (!isReading) return;
    let on = true;
    const tick = async () => {
      const ok = await read();
      if (on && ok && feed.value === "lost") feed.value = "poll"; // the API answers again
    };
    if (hasEnded) void tick();
    const id = setInterval(() => void tick(), POLL_MS);
    onCleanup(() => {
      on = false;
      clearInterval(id);
    });
  },
  { immediate: true },
);

const lines = computed(() => stepLines(events.value));
const last = computed(() => events.value[events.value.length - 1]);
const final = computed(() => events.value.find(isTerminal));

// The rail's sections and states, read for this run's report once the run is known, and again when it ends (the draft it
// saved is then the section's current review).
const rereadRail = () => run.value && void shell.refreshFor(run.value.report_type, run.value.period);
watch(() => run.value?.run_id, rereadRail, { immediate: true });
watch(final, (now) => now && rereadRail());

// Keep the newest line in view, but only for someone already at the foot of the page: scrolling up to read
// an earlier step is never undone.
let following = true;
const foot = useTemplateRef<HTMLDivElement>("foot");
const onScroll = () => {
  following = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - FOLLOW_PX;
};
onMounted(() => window.addEventListener("scroll", onScroll, { passive: true }));
onUnmounted(() => window.removeEventListener("scroll", onScroll));
watch([() => lines.value.length, settled], async () => {
  await nextTick();
  if (following) foot.value?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
});

// The top bar's Back: to the run's own report's list of sections (as the masthead's back link did before the bar).
const backHref = computed(() => (run.value ? overviewHref(run.value.report_type, run.value.period) : "/overview"));
useBack((): BackTarget => ({ kind: "href", to: "all sections", href: backHref.value }));

const devLabel = computed(() => run.value?.dev_mode_label ?? config.value?.dev_mode_label ?? "");
const dev = computed(() => (run.value?.is_dev_draft === true || (config.value?.dev_mode === true && !settled.value)) && !!devLabel.value);
useShellRibbon(() => (dev.value ? devLabel.value : null)); // the shell draws it under the top bar
const weekly = computed(() => (run.value ? run.value.report_type === "weekly" && !run.value.period : true));
const failed = computed(() => final.value?.kind === "run_failed");
const still = computed(() => reduced || feed.value === "lost");
const status = computed(() => {
  if (!last.value) return run.value ? "Waiting for the draft to start." : feed.value === "lost" ? "Not connected." : "Loading the run…";
  if (final.value) return `${failed.value ? "Stopped" : "Finished"} ${friendlyTime(final.value.at)}.`;
  return `Running. Started ${friendlyTime(events.value[0].at)}.`;
});
</script>

<template>
  <main id="main" tabindex="-1">
    <!-- This run's section and report are in the title block; the steps and what came of the run are the feed, and its
         facts are the panel beside it. Nothing that has to be seen is in the panel: the status, the notices, the failure
         and the ways back to the overview are in the feed, as they always were. -->
    <Masthead wide :title="run && !missing ? `${run.section_title}: draft run` : 'Draft run'">
      <template v-if="run && !missing && !weekly" #meta><span class="font-mono">{{ run.period }}</span></template>
      <template v-if="run && !missing" #default>{{ reportName(run.report_title, run.period) }}. Each line below is a step the draft has really taken.</template>
    </Masthead>

    <!-- Keyed on whether the run is gone: the grid reads which slots it has once, and a run that is gone has no panel. -->
    <PageGrid :key="missing ? 'gone' : 'run'" aside-title="This run">
      <div v-if="missing" class="space-y-6">
        <Notice tone="warn" role="status">
          This run is no longer available. If the draft finished, open the section from the overview.
          <RouterLink to="/overview" :class="LINK">Go to the overview</RouterLink>
        </Notice>
      </div>

      <div v-else class="space-y-6">
        <p role="status" class="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
          <span class="font-semibold">{{ status }}</span>
          <span v-if="!final && feed === 'poll'" class="text-muted-foreground">Live updates are off; checking every 2 seconds.</span>
        </p>

        <Notice v-if="feed === 'lost' && !settled" tone="warn" role="alert">
          Connection lost. The draft may still finish. Check the overview before starting another.
          <RouterLink :to="backHref" :class="LINK">Go to the overview</RouterLink>
        </Notice>

        <section aria-labelledby="steps-title">
          <h2 id="steps-title" class="eyebrow pb-2">Steps</h2>
          <!-- Empty until the first event arrives: no placeholder moves while nothing has happened. -->
          <ol role="log" aria-label="Steps of this draft" class="rounded-lg border bg-card" :class="lines.length === 0 && 'hidden'">
            <li v-for="line in lines" :key="line.key" class="flex items-start gap-3 border-b px-4 py-3 last:border-b-0" :class="!reduced && 'rise-in'">
              <span v-if="line.mark === 'failed'" class="state-flagged" aria-hidden="true"><span class="glyph">!</span></span>
              <span v-else-if="line.mark === 'skipped'" :class="[BOX, 'border border-dashed border-input text-muted-foreground']" aria-hidden="true">
                <PhMinus weight="bold" class="size-3" />
              </span>
              <span v-else-if="line.mark === 'done'" :class="[BOX, 'border border-input text-foreground']" aria-hidden="true">
                <PhCheck weight="bold" class="size-3" />
              </span>
              <!-- Working: it spins only while it is the run's latest unfinished step and this screen is still hearing
                   from the run; never under reduced motion, and not once the connection is lost. -->
              <span v-else :class="[BOX, 'text-foreground']" aria-hidden="true">
                <PhCircleNotch weight="bold" class="size-4" :class="line.active && !still && 'animate-spin'" />
              </span>
              <p class="min-w-0 text-sm wrap-break-word" :class="[line.mark === 'skipped' && 'text-muted-foreground', line.mark === 'failed' && 'font-medium']">
                <span class="sr-only">{{ MARK_WORD[line.mark] }}: </span>{{ line.text }}
              </p>
            </li>
          </ol>
          <p v-if="lines.length === 0" class="text-sm text-muted-foreground">No steps yet.</p>
        </section>

        <section
          v-if="final?.kind === 'run_finished'"
          aria-labelledby="result-title"
          class="space-y-4 rounded-lg border border-t-[3px] border-t-primary bg-card p-6"
          :class="!reduced && 'rise-in'"
        >
          <h2 id="result-title" class="text-lg font-semibold">Draft ready for review</h2>
          <Notice v-if="run?.is_dev_draft && run.dev_mode_label" role="alert" class="font-semibold">{{ run.dev_mode_label }}</Notice>
          <div role="group" aria-label="Review items by status" class="grid grid-cols-1 gap-3 @min-[34rem]:grid-cols-3">
            <CountTile v-for="s in STATUS_ORDER" :key="s" :status="s" :value="final.counts?.[s] ?? 0" />
          </div>
          <RouterLink
            v-if="run?.review_id != null"
            :to="overviewHref(run.report_type, run.period, run.review_id)"
            data-slot="button"
            :class="cn(buttonVariants({ size: 'lg' }))"
          >
            Open review
          </RouterLink>
          <Button v-else size="lg" disabled>Open review</Button>
        </section>

        <div v-if="failed && final" class="space-y-3">
          <Notice role="alert" class="font-medium">The draft stopped.{{ final.detail ? ` ${final.detail}` : "" }}</Notice>
          <p class="text-sm">
            <RouterLink :to="backHref" :class="LINK">Back to overview</RouterLink>
          </p>
        </div>

        <div ref="foot" aria-hidden="true" />
      </div>

      <template v-if="!missing" #aside>
        <dl v-if="run" class="space-y-3 text-sm">
          <div>
            <dt class="eyebrow">Section</dt>
            <dd class="font-medium">{{ run.section_title }}</dd>
          </div>
          <div>
            <dt class="eyebrow">Report</dt>
            <dd class="font-medium">{{ reportName(run.report_title, run.period) }}</dd>
          </div>
          <div v-if="events.length > 0">
            <dt class="eyebrow">Started</dt>
            <dd class="font-medium">{{ friendlyTime(events[0].at) }}</dd>
          </div>
          <div v-if="final">
            <dt class="eyebrow">{{ failed ? "Stopped" : "Finished" }}</dt>
            <dd class="font-medium">{{ friendlyTime(final.at) }}</dd>
          </div>
        </dl>
        <p v-else class="text-sm text-muted-foreground">Not read yet.</p>
      </template>
    </PageGrid>
  </main>
</template>
