<script setup lang="ts">
import { PhArrowRight, PhCaretDown, PhCloudArrowDown, PhUploadSimple } from "@phosphor-icons/vue";
import { computed, ref, shallowRef, watch } from "vue";
import { RouterLink } from "vue-router";
import ExportBar from "@/components/review/ExportBar.vue";
import Notice from "@/components/review/Notice.vue";
import RedraftDialog from "@/components/review/RedraftDialog.vue";
import Button from "@/components/ui/Button.vue";
import { LINK, buttonVariants } from "@/components/ui/button";
import * as api from "@/lib/api";
import { GROUPS, type Readiness, type ReadinessEntry, captureSteps, draftCard, needsYou, parseReadiness, sourceRows, weekOf } from "@/lib/chatcards";
import { useDraftStart } from "@/lib/draftstart";
import { MARKS } from "@/lib/railmarks";
import type { RailState } from "@/lib/shell";
import type { AppConfig, Drafting, ReportChoice, SectionSummary } from "@/lib/types";
import PrepareInputs from "./PrepareInputs.vue";

const props = defineProps<{
  section: SectionSummary;
  report: ReportChoice;
  config: AppConfig | null;
  drafting: Drafting | null;
  state: RailState | null;
  /** The old page's address for this section: the inputs form. */
  oldPage: string;
  /** The address of this section's conversation view. */
  conversationTo: string;
}>();
const emit = defineEmits<{ changed: []; conversation: [] }>();

const week = computed(() => weekOf(props.report.period));
const readiness = shallowRef<Readiness | null>(null);
const talked = ref(false);
const readProblem = ref<string | null>(null);
let generation = 0;
const steps = shallowRef<ReadinessEntry[] | null>(null);
let rowOrder: string[] = [];

/** Read with GET /api/sections/{slug}/readiness: no conversation is opened and no model is called. */
async function read() {
  const mine = ++generation;
  try {
    const got = await api.getSectionReadiness(props.section.slug, props.report.period);
    if (mine !== generation) return;
    readiness.value = parseReadiness(got.readiness);
    talked.value = got.conversation === true;
    readProblem.value = readiness.value ? null : "The readiness check came back in a shape this page does not know.";
  } catch (err) {
    if (mine === generation) readProblem.value = (err as Error).message;
  }
}
watch(() => `${props.section.slug} ${props.report.period}`, () => {
  readiness.value = null;
  steps.value = null;
  rowOrder = [];
  void read();
}, { immediate: true });

function done() {
  emit("changed");
  void read();
}

// ---- The banner and its checklist ----
const required = computed(() => readiness.value?.groups.needs_analyst.length ?? 0);
const optional = computed(() => readiness.value?.groups.optional.length ?? 0);
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const checklistOpen = ref(false);

// ---- Card 1: source documents, in the order first seen ----
const rows = computed(() => {
  if (!readiness.value) return [];
  const got = sourceRows(readiness.value, rowOrder);
  if (!rowOrder.length) rowOrder = got.map((r) => r.key);
  return got;
});
const busy = ref<string | null>(null);
const actionProblem = ref<string | null>(null);
const picked = ref<Record<string, string>>({});

async function act(key: string, call: () => Promise<unknown>) {
  busy.value = key;
  actionProblem.value = null;
  try {
    await call();
  } catch (err) {
    actionProblem.value = (err as Error).message;
  } finally {
    busy.value = null;
    done();
  }
}
const fetchRow = (key: string) => act(`fetch-${key}`, () => (key === "cbk_bulletin" ? api.fetchBulletin(week.value) : api.fetchAnalystTable(week.value, props.section.slug, key)));
async function upload(slot: string, event: Event) {
  const input = event.target as HTMLInputElement;
  const files = [...(input.files ?? [])];
  input.value = "";
  if (!files.length) return;
  picked.value = { ...picked.value, [slot]: files.map((f) => f.name).join(", ") };
  await act(`upload-${slot}`, async () => {
    const refused: string[] = [];
    for (const file of files) {
      try {
        await api.uploadInput(week.value, slot, file);
      } catch (err) {
        refused.push(`${file.name}: ${(err as Error).message}`);
      }
    }
    if (refused.length) throw new Error(refused.join("\n"));
  });
}

// ---- Card 2: the typed steps, captured once ----
const needs = computed(() => (readiness.value ? needsYou(readiness.value) : null));
watch(needs, (n) => (steps.value = captureSteps(steps.value, n?.inline ?? [])));
const formOnly = computed(() => (needs.value ? [...needs.value.typed, ...needs.value.confirm] : []));
const hasInputs = computed(() => (steps.value?.length ?? 0) + formOnly.value.length > 0);

// ---- Card 3: create the draft. The conversation is opened first, exactly as picking the section does, so the draft's
// review summary has a conversation to land in; then the draft card's own start, questions dialog included. ----
const card = computed(() => draftCard(props.section, props.drafting, props.config));
const opening = ref(false);
const openProblem = ref<string | null>(null);
const { starting, problem, asking, start, draft } = useDraftStart(
  { section: () => props.section, report: () => props.report, config: () => props.config },
  () => {
    emit("changed");
    if (!problem.value) emit("conversation");
  },
);
async function create() {
  opening.value = true;
  openProblem.value = null;
  try {
    await api.chatApi.open(props.section.slug, props.report.period);
  } catch (err) {
    openProblem.value = (err as Error).message;
    return;
  } finally {
    opening.value = false;
  }
  await start();
}
/** Cancelled in the questions dialog: the conversation is open and no draft starts, as when cancelling in the chat. */
function cancelled() {
  asking.value = null;
  emit("conversation");
}

const n = computed(() => ({ inputs: rows.value.length ? 2 : 1, draft: (rows.value.length ? 1 : 0) + (hasInputs.value ? 1 : 0) + 1 }));
const exportProblem = ref<string | null>(null);
const mark = computed(() => MARKS[props.state ?? "unknown"]);
</script>

<template>
  <div class="space-y-5" data-card="prepare">
    <div class="space-y-1">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <h2 id="chat-title" class="text-2xl font-semibold tracking-tight">{{ section.title }}</h2>
        <span class="inline-flex items-center gap-1.5 rounded-sm bg-cw-chip px-2.5 py-1 text-xs font-semibold text-foreground">
          <component :is="mark.icon" weight="bold" class="size-3.5" aria-hidden="true" />{{ mark.label }}
        </span>
      </div>
      <p class="text-sm text-muted-foreground">Week ending {{ week }} · Prepare your sources and inputs, then create a draft.</p>
      <RouterLink v-if="talked" :to="conversationTo" :class="['inline-flex min-h-11 items-center text-sm', LINK]">Open the conversation</RouterLink>
    </div>

    <Notice v-if="readProblem" tone="warn" role="alert">{{ readProblem }}</Notice>
    <p v-else-if="!readiness" class="text-sm text-muted-foreground" aria-busy="true">Reading what this section needs…</p>

    <template v-else>
      <div class="rounded-lg bg-cw-bubble px-4 py-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p aria-live="polite" class="flex flex-wrap items-baseline gap-x-3 text-sm">
            <span class="font-semibold">{{ required ? `${plural(required, "required item", "required items")} missing` : "Everything required is in place" }}</span>
            <span v-if="optional" class="text-xs text-muted-foreground">{{ plural(optional, "optional item", "optional items") }}</span>
          </p>
          <Button variant="outline" class="min-h-11 bg-card" :aria-expanded="checklistOpen" aria-controls="prepare-checklist" @click="checklistOpen = !checklistOpen">
            {{ checklistOpen ? "Hide checklist" : "View checklist" }}<PhCaretDown weight="bold" data-icon="inline-end" :class="checklistOpen && 'rotate-180'" aria-hidden="true" />
          </Button>
        </div>
        <div v-show="checklistOpen" id="prepare-checklist" class="mt-3 space-y-3 border-t pt-3">
          <template v-for="g in GROUPS" :key="g.key">
            <div v-if="readiness.groups[g.key].length" class="space-y-1">
              <p class="text-sm font-semibold">{{ g.heading }} ({{ readiness.groups[g.key].length }})</p>
              <p class="text-xs text-muted-foreground">{{ g.meaning }}</p>
              <ul class="list-disc space-y-0.5 pl-5 text-sm [overflow-wrap:anywhere]">
                <li v-for="e in readiness.groups[g.key]" :key="e.key">{{ e.label }}: {{ e.why }}</li>
              </ul>
            </div>
          </template>
        </div>
      </div>

      <section v-if="rows.length" aria-labelledby="prepare-sources-title" class="space-y-3 rounded-lg border p-4 sm:p-6" data-card="prepare_sources">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="prepare-sources-title" class="text-lg font-semibold"><span class="mr-2 tabular-nums">1</span>Source documents</h3>
          <p class="text-sm text-muted-foreground tabular-nums">{{ rows.filter((r) => r.added).length }} of {{ rows.length }} added</p>
        </div>
        <!-- Explicit roles: on a phone the rows are restyled as stacked blocks, and the roles keep them a table to a screen reader. -->
        <table role="table" class="w-full text-sm max-sm:block">
          <thead role="rowgroup" class="max-sm:sr-only">
            <tr role="row" class="text-left text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              <th role="columnheader" scope="col" class="py-2 pr-3 font-semibold">Document</th>
              <th role="columnheader" scope="col" class="py-2 pr-3 font-semibold">Status</th>
              <th role="columnheader" scope="col" class="py-2 text-right font-semibold whitespace-nowrap">Action</th>
            </tr>
          </thead>
          <tbody role="rowgroup" class="max-sm:block">
            <tr v-for="r in rows" :key="r.key" role="row" class="border-t align-middle max-sm:block max-sm:py-3">
              <th role="rowheader" scope="row" class="py-2.5 pr-3 text-left font-medium max-sm:block max-sm:p-0">{{ r.label }}</th>
              <td role="cell" class="py-2.5 pr-3 text-muted-foreground max-sm:block max-sm:p-0">
                {{ r.status }}
                <span v-if="picked[r.key]" class="block text-xs text-foreground [overflow-wrap:anywhere]">Chosen: {{ picked[r.key] }}</span>
              </td>
              <td role="cell" class="py-2.5 max-sm:block max-sm:pt-2">
                <div class="flex justify-end gap-2 max-sm:flex-wrap max-sm:justify-start">
                  <Button v-if="r.fetch" variant="outline" class="min-h-11" :disabled="busy !== null" @click="fetchRow(r.key)">
                    <PhCloudArrowDown weight="bold" data-icon="inline-start" aria-hidden="true" />
                    {{ busy === `fetch-${r.key}` ? "Fetching…" : r.fetch }}<span class="sr-only">: {{ r.label }}</span>
                  </Button>
                  <label v-if="r.upload" :class="[buttonVariants({ variant: 'outline' }), 'min-h-11 cursor-pointer has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50']">
                    <input type="file" multiple accept=".pdf,.xlsx" :disabled="busy !== null" :aria-label="`Upload ${r.label}`" class="sr-only" @change="upload(r.key, $event)" />
                    <PhUploadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
                    <span aria-hidden="true">{{ busy === `upload-${r.key}` ? "Uploading…" : "Upload" }}</span>
                  </label>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <Notice v-if="actionProblem" role="alert" class="font-medium whitespace-pre-line">{{ actionProblem }}</Notice>
      </section>

      <PrepareInputs
        v-if="hasInputs"
        :steps="steps ?? []"
        :form-only="formOnly"
        :week="week"
        :section="section.slug"
        :form-to="oldPage"
        :n="n.inputs"
        @changed="done"
      />

      <section aria-labelledby="prepare-draft-title" class="rounded-lg border p-4 sm:p-6" data-card="prepare_draft">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0 flex-1 basis-72 space-y-1">
            <h3 id="prepare-draft-title" class="text-lg font-semibold"><span class="mr-2 tabular-nums">{{ n.draft }}</span>Create draft</h3>
            <p class="text-sm text-muted-foreground">Draft this section using what’s in place. Anything still missing comes back as a named gap, never as invented text.</p>
            <p v-if="card.kind === 'blocked' || card.kind === 'none'" class="text-sm">{{ card.why }}</p>
            <p v-else-if="card.kind === 'running' || card.kind === 'queued'" class="text-sm">This section is being drafted. <RouterLink :to="conversationTo" :class="LINK">Open the conversation</RouterLink> to follow it.</p>
          </div>
          <div v-if="card.kind === 'ready' || card.kind === 'failed'" class="space-y-1 text-center max-sm:w-full">
            <Button class="min-h-11 px-6 max-sm:w-full" :disabled="opening || starting" @click="create">
              {{ opening || starting ? "Starting…" : "Create draft" }}<PhArrowRight weight="bold" data-icon="inline-end" aria-hidden="true" />
            </Button>
            <p class="text-xs text-muted-foreground">{{ required ? `${plural(required, "required item", "required items")} still missing` : "Everything required is in place" }}</p>
          </div>
        </div>
        <Notice v-if="openProblem || problem" role="alert" class="mt-3 font-medium">{{ openProblem || problem }}</Notice>
        <RedraftDialog :open="asking !== null" title="Draft this section?" :notes="asking ?? []" confirm-label="Draft anyway" @confirm="draft" @cancel="cancelled" />
      </section>

      <ExportBar rows :period="report.period" :refresh-key="`${section.latest?.run_id ?? 0}-${section.latest?.decision ?? ''}`" @error="(m) => (exportProblem = m)" />
      <Notice v-if="exportProblem" role="alert" class="font-medium">{{ exportProblem }}</Notice>
    </template>
  </div>
</template>
