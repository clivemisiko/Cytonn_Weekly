<script setup lang="ts">
import { PhCheck, PhCircleNotch, PhMinus, PhPlay, PhWarningCircle } from "@phosphor-icons/vue";
import { computed, onUnmounted, ref, shallowRef, watch } from "vue";
import Notice from "@/components/review/Notice.vue";
import RedraftDialog from "@/components/review/RedraftDialog.vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { type DraftCard as Card, weekOf } from "@/lib/chatcards";
import { draftChartsNote } from "@/lib/charts";
import { queueText } from "@/lib/drafting";
import { redraftNotes } from "@/lib/redraft";
import { mergeEvents, stepLines } from "@/lib/run";
import { missingSourcesNote, piecesNothingFoundFor, usesSources } from "@/lib/sources";
import type { AppConfig, ReportChoice, RunEvent, SectionSummary } from "@/lib/types";

const POLL_MS = 2_000;
const props = defineProps<{ section: SectionSummary; card: Card; report: ReportChoice; config: AppConfig | null }>();
const emit = defineEmits<{ changed: []; ended: [] }>();

const starting = ref(false);
const problem = ref<string | null>(null);
const asking = ref<string[] | null>(null);
const startedRun = ref<string | null>(null);

const week = computed(() => weekOf(props.report.period));
const runId = computed(() => (props.card.kind === "running" || props.card.kind === "queued" ? (props.card.drafting.run_id ?? startedRun.value) : startedRun.value));

/** The questions the old start screen asks before a draft, asked together in one dialog: charts with no image, pieces a search found
 *  nothing for, and what a new draft does to an earlier review. */
async function notes(): Promise<string[]> {
  const out: string[] = [];
  const slug = props.section.slug;
  if (slug === "fixed_income" || slug === "equities") {
    try {
      const note = draftChartsNote((await api.getInputs(week.value)).charts ?? [], slug);
      if (note) out.push(note);
    } catch {
      /* a failed read never stops a draft */
    }
  }
  if (props.config && usesSources(props.config, props.section) && slug !== "real_estate") {
    try {
      const note = missingSourcesNote(piecesNothingFoundFor((await api.getSources(slug, props.report)).pieces));
      if (note) out.push(note);
    } catch {
      /* the same */
    }
  }
  const earlier = props.section.latest;
  if (earlier && (earlier.current ?? earlier.this_week)) out.push(...redraftNotes(earlier, props.report.type, props.section.requires_approved));
  return out;
}

async function start() {
  problem.value = null;
  starting.value = true;
  try {
    const found = await notes();
    if (found.length) asking.value = found;
    else await draft();
  } finally {
    starting.value = false;
  }
}

async function draft() {
  asking.value = null;
  starting.value = true;
  problem.value = null;
  try {
    const started = await api.startRun(props.section.slug, props.report, { provider: props.section.uses_provider ? props.config?.provider : undefined });
    startedRun.value = started.run_id;
  } catch (err) {
    problem.value = (err as Error).message;
  } finally {
    starting.value = false;
    emit("changed");
  }
}

// ---- A draft under way: its real steps, read every two seconds; nothing here is timed or guessed ----
const events = shallowRef<RunEvent[]>([]);
const status = ref<string | null>(null);
const position = ref<number | null>(null);
const cancelError = ref<string | null>(null);
const cancelling = ref(false);
const lines = computed(() => stepLines(events.value));
const queued = computed(() => status.value === "queued" || (status.value === null && props.card.kind === "queued"));

let timer: ReturnType<typeof setInterval> | null = null;
function stop() {
  if (timer !== null) clearInterval(timer);
  timer = null;
}
async function read(id: string) {
  try {
    const run = await api.getRun(id);
    events.value = mergeEvents(events.value, run.events);
    status.value = run.status;
    position.value = run.position ?? null;
    if (run.status !== "running" && run.status !== "queued") {
      stop();
      emit("ended");
    }
  } catch (err) {
    if ((err as api.ApiError).status === 404) stop(); // the API restarted: the saved record says what happened
  }
}
watch(
  runId,
  (id) => {
    stop();
    events.value = [];
    status.value = null;
    if (!id) return;
    void read(id);
    timer = setInterval(() => void read(id), POLL_MS);
  },
  { immediate: true },
);
onUnmounted(stop);

async function cancel() {
  if (!runId.value) return;
  cancelling.value = true;
  cancelError.value = null;
  try {
    await api.cancelRun(runId.value);
    await read(runId.value);
  } catch (err) {
    cancelError.value = (err as Error).message;
  } finally {
    cancelling.value = false;
    emit("changed");
  }
}

const MARK = { working: PhCircleNotch, done: PhCheck, skipped: PhMinus, failed: PhWarningCircle } as const;
const MARK_WORD = { working: "In progress", done: "Done", skipped: "Skipped", failed: "Failed" } as const;
const underway = computed(() => props.card.kind === "running" || props.card.kind === "queued" || (startedRun.value !== null && status.value !== null && status.value !== "finished" && status.value !== "failed"));
</script>

<template>
  <section aria-label="Draft" class="space-y-2 rounded-md border bg-background px-3 py-2.5" :data-card="underway ? 'draft_running' : 'draft_ready'">
    <template v-if="underway">
      <h3 class="text-sm font-semibold">{{ queued ? "Draft queued" : "Draft running" }}</h3>
      <p role="status" class="text-sm">
        <template v-if="queued">{{ queueText(position ?? (card.kind === "queued" ? card.drafting.position : null)) }} It starts by itself when a drafting seat is free.</template>
        <template v-else>The draft is being written. Each step below is what the pipeline reported.</template>
      </p>
      <ol v-if="lines.length" class="space-y-1 text-sm" aria-label="Draft steps">
        <li v-for="l in lines" :key="l.key" class="flex items-start gap-2">
          <component :is="MARK[l.mark]" weight="bold" class="mt-0.5 size-4 shrink-0" :class="l.active && 'animate-spin motion-reduce:animate-none'" aria-hidden="true" />
          <span><span class="sr-only">{{ MARK_WORD[l.mark] }}: </span>{{ l.text }}</span>
        </li>
      </ol>
      <div v-if="queued" class="space-y-2">
        <Button variant="outline" size="sm" :disabled="cancelling || !runId" @click="cancel">Cancel this draft</Button>
        <Notice v-if="cancelError" role="alert" class="font-medium">{{ cancelError }}</Notice>
      </div>
      <p v-else class="text-xs text-muted-foreground">A draft that is running cannot be stopped. It saves its review when it finishes.</p>
    </template>

    <template v-else>
      <h3 class="text-sm font-semibold">{{ card.kind === "ready" && card.again ? "Draft this section again" : "Ready to draft" }}</h3>
      <p v-if="card.kind === 'ready'" class="text-sm text-muted-foreground">
        The tool drafts the section from what is in place. {{ card.again ? "The earlier review stays saved; the new draft becomes the current one." : "Anything still missing comes back as a named gap, never as invented text." }}
      </p>
      <p v-else-if="card.kind === 'failed'" class="flex items-start gap-1.5 text-sm"><PhWarningCircle weight="bold" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />The last draft stopped. {{ card.why }}</p>
      <p v-else-if="card.kind === 'blocked' || card.kind === 'none'" class="text-sm text-muted-foreground">{{ card.why }}</p>
      <Button v-if="card.kind === 'ready' || card.kind === 'failed'" :disabled="starting" @click="start">
        <PhPlay weight="bold" data-icon="inline-start" aria-hidden="true" />
        {{ starting ? "Starting…" : card.kind === "failed" || (card.kind === "ready" && card.again) ? "Start draft again" : "Start draft" }}
      </Button>
      <Notice v-if="problem" role="alert" class="font-medium">{{ problem }}</Notice>
    </template>

    <RedraftDialog
      :open="asking !== null"
      title="Draft this section?"
      :notes="asking ?? []"
      confirm-label="Draft anyway"
      @confirm="draft"
      @cancel="asking = null"
    />
  </section>
</template>
