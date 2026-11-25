<script setup lang="ts">
import { PhArrowRight, PhCaretDown, PhCloudArrowDown, PhTrash, PhUploadSimple } from "@phosphor-icons/vue";
import { computed, ref, shallowRef, watch } from "vue";
import { RouterLink } from "vue-router";
import ExportBar from "@/components/review/ExportBar.vue";
import ExportNotices from "@/components/review/ExportNotices.vue";
import Notice from "@/components/review/Notice.vue";
import RedraftDialog from "@/components/review/RedraftDialog.vue";
import SnipSector from "@/components/review/SnipSector.vue";
import SourcesPanel from "@/components/review/SourcesPanel.vue";
import Button from "@/components/ui/Button.vue";
import UploadProgress from "@/components/ui/UploadProgress.vue";
import { LINK, buttonVariants } from "@/components/ui/button";
import * as api from "@/lib/api";
import { type KeptFile, type Readiness, draftCard, hasDraftWork, parseReadiness, sourceRows, weekOf } from "@/lib/chatcards";
import { useDraftStart } from "@/lib/draftstart";
import { usePart } from "@/lib/loadpart";
import { SHOW_CHAT } from "@/lib/features";
import { type Step, focusProblems, noDocumentsLine, openingStep, plural, prepareCounts, prepareSteps, readFocus, writeFocus } from "@/lib/prepare";
import { MARKS } from "@/lib/railmarks";
import type { RailState } from "@/lib/shell";
import { usesSources } from "@/lib/sources";
import { MAX_SECTIONS, MAX_SECTION_TITLE, MAX_TOPIC, sectionTitles, sectionsProblem, topicLength } from "@/lib/topic";
import type { AnalystForm, AppConfig, Drafting, ExportStatus, ReportChoice, SectionSummary, SourcePiece } from "@/lib/types";
import { useSnips } from "@/lib/usesnips";
import FundSnipCard from "./FundSnipCard.vue";
import InputSteps from "./InputSteps.vue";

const props = defineProps<{
  section: SectionSummary;
  report: ReportChoice;
  config: AppConfig | null;
  drafting: Drafting | null;
  state: RailState | null;
  /** The address of this section's conversation view. */
  conversationTo: string;
  /** A step the address names, to open on. */
  openOn?: string | null;
}>();
const emit = defineEmits<{ changed: []; conversation: [] }>();

const week = computed(() => weekOf(props.report.period));
const readiness = shallowRef<Readiness | null>(null);
const form = shallowRef<AnalystForm | null>(null);
const pieces = shallowRef<SourcePiece[] | null>(null);
const talked = ref(false);
const shapeProblem = ref<string | null>(null);
const steps = shallowRef<Step[] | null>(null);
let rowOrder: string[] = [];

// What the section is made of follows from its data: a form when the readiness check lists typed items, snips when it
// counts snips, a topic when the section needs one, sources when the drafting engine searches.
const hasForm = computed(() => !!readiness.value && Object.values(readiness.value.groups).some((g) => g.some((e) => e.kind !== "upload")));
const bedrock = computed(() => !!props.config && usesSources(props.config, props.section));
// A section written from snips takes no sources (the API refuses them), as on the old start screen; readiness says which sections those are.
const takesSources = computed(() => bedrock.value && !readiness.value?.snips);
const snips = useSnips(week);

// Each read on its own: one that fails keeps what the others drew, and its Try again repeats only it.
const readinessCall = usePart(() => api.getSectionReadiness(props.section.slug, props.report.period));
const formCall = usePart(() => api.getAnalystInputs(week.value, props.section.slug));
const readProblem = computed(() => readinessCall.problem.value ?? shapeProblem.value);

/** Read with GET /api/sections/{slug}/readiness: no conversation is opened and no model is called. */
async function read() {
  if (!(await readinessCall.run())) return;
  const got = readinessCall.value.value!;
  readiness.value = parseReadiness(got.readiness);
  talked.value = got.conversation === true;
  shapeProblem.value = readiness.value ? null : "The readiness check came back in a shape this page does not know.";
  if (readiness.value?.snips && !snips.listing.value) await snips.load();
  if (hasForm.value && !form.value) await readForm();
}

async function readForm() {
  if (await formCall.run()) form.value = formCall.value.value;
}

// ---- Focus of the Week: the topic and titles live on this page, mirrored to session storage for a reload ----
const topic = ref("");
const titles = ref("");
watch(
  () => `${props.section.slug} ${props.report.period}`,
  () => {
    readinessCall.reset();
    formCall.reset();
    shapeProblem.value = null;
    readiness.value = null;
    form.value = null;
    pieces.value = null;
    steps.value = null;
    snips.listing.value = null;
    rowOrder = [];
    ({ topic: topic.value, titles: titles.value } = props.section.needs_topic ? readFocus(props.report.period, props.section.slug) : { topic: "", titles: "" });
    void read();
  },
  { immediate: true },
);
watch([topic, titles], ([t, s]) => props.section.needs_topic && writeFocus(props.report.period, props.section.slug, { topic: t, titles: s }));
const focus = computed(() => (props.section.needs_topic ? { topic: topic.value, titles: titles.value, bedrock: bedrock.value } : null));
const topicOver = computed(() => topicLength(topic.value) > MAX_TOPIC);
const titlesError = computed(() => sectionsProblem(titles.value));

function done() {
  emit("changed");
  void read();
}

// ---- The counts: one function for the banner, the checklist and the caption ----
const counts = computed(() => (readiness.value ? prepareCounts(readiness.value, { snips: snips.listing.value, sources: pieces.value, focus: focus.value }) : null));
const checklistOpen = ref(false);

// ---- Card 2: every input, in one fixed order, captured once everything it is built from has been read ----
watch(
  [readiness, form, snips.listing],
  () => {
    if (steps.value || !readiness.value || (hasForm.value && !form.value) || (readiness.value.snips && !snips.listing.value)) return;
    steps.value = prepareSteps({ form: form.value, sectors: snips.listing.value?.sectors ?? [], topic: props.section.needs_topic, sources: takesSources.value });
  },
  { immediate: true },
);
const start = computed(() => (steps.value && counts.value ? openingStep(steps.value, counts.value.missing, props.openOn) : 0));
const sectorOf = (key: string) => snips.bySector.value.find((s) => `snips:${s.id}` === key);

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
  // Done either way: the row shows what the server now holds, and a refusal is said in the alert below the table.
  const rest = { ...picked.value };
  delete rest[slot];
  picked.value = rest;
}

// Removing a kept file: this week's inputs only (DELETE /api/inputs/weekly/{week}/{stored name}); no run, review or history is touched.
const removing = ref<{ label: string; file: KeptFile } | null>(null);
function removeFile() {
  const asked = removing.value;
  removing.value = null;
  if (asked) void act(`remove-${asked.file.storedName}`, () => api.removeInput(week.value, asked.file.storedName));
}

// ---- Card 3: create the draft. The conversation is opened first, exactly as picking the section does, so the draft's
// review summary has a conversation to land in; then the draft card's own start, questions dialog included. ----
const card = computed(() => draftCard(props.section, props.drafting, props.config, true));
const focusMissing = computed(() => (focus.value ? focusProblems(topic.value, titles.value, bedrock.value) : []));
// Off, but still focusable: a keyboard user reaches the button and hears its caption say why.
const blocked = computed(() => opening.value || starting.value || focusMissing.value.length > 0);
const opening = ref(false);
const openProblem = ref<string | null>(null);
const { starting, problem, asking, start: startDraft, draft } = useDraftStart(
  { section: () => props.section, report: () => props.report, config: () => props.config, focus: () => focus.value },
  () => {
    emit("changed");
    if (problem.value) return;
    if (props.section.needs_topic) writeFocus(props.report.period, props.section.slug, null); // the draft has them now
    emit("conversation");
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
  await startDraft();
}
/** Cancelled in the questions dialog: the conversation is open and no draft starts, as when cancelling in the chat. */
function cancelled() {
  asking.value = null;
  emit("conversation");
}
const caption = computed(() => {
  if (focusMissing.value.length) return `Still needed: ${focusMissing.value.join(" and ")}`;
  const n = counts.value?.required ?? 0;
  return n ? `${plural(n, "required item", "required items")} still missing` : "Everything required is in place";
});

const exportProblem = ref<string | null>(null);
const exportStatus = ref<ExportStatus | null>(null);
const mark = computed(() => MARKS[props.state ?? "unknown"]);
</script>

<template>
  <div class="space-y-5" data-card="prepare">
    <div class="space-y-1">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <h2 id="chat-title" class="text-2xl font-semibold tracking-tight">{{ section.title }}</h2>
        <span class="inline-flex items-center gap-1.5 rounded-sm bg-cw-chip px-2.5 py-1 text-xs font-semibold text-foreground" data-pill>
          <component :is="mark.icon" weight="bold" class="size-3.5" aria-hidden="true" />{{ mark.label }}
        </span>
      </div>
      <p class="text-sm text-muted-foreground">Week ending {{ week }} · Prepare your sources and inputs, then create a draft.</p>
      <RouterLink v-if="SHOW_CHAT && talked" :to="conversationTo" :class="['inline-flex min-h-11 items-center text-sm', LINK]">Open the conversation</RouterLink>
    </div>

    <div v-if="readProblem" class="flex flex-wrap items-center gap-3" data-part-problem="readiness">
      <Notice tone="warn" role="alert" class="flex-1">{{ readProblem }}</Notice>
      <Button variant="outline" class="min-h-11" @click="read">Try again</Button>
    </div>
    <p v-if="!readProblem && (!readiness || !counts)" class="text-sm text-muted-foreground" aria-busy="true">Reading what this section needs…</p>

    <template v-if="readiness && counts">
      <div class="rounded-lg bg-cw-bubble px-4 py-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p aria-live="polite" class="flex flex-wrap items-baseline gap-x-3 text-sm" data-banner>
            <span class="font-semibold">{{ counts.required ? `${plural(counts.required, "required item", "required items")} missing` : "Everything required is in place" }}</span>
            <span v-if="counts.optional" class="text-xs text-muted-foreground">{{ plural(counts.optional, "optional item", "optional items") }}</span>
          </p>
          <Button variant="outline" class="min-h-11 bg-card" :aria-expanded="checklistOpen" aria-controls="prepare-checklist" @click="checklistOpen = !checklistOpen">
            {{ checklistOpen ? "Hide checklist" : "View checklist" }}<PhCaretDown weight="bold" data-icon="inline-end" :class="checklistOpen && 'rotate-180'" aria-hidden="true" />
          </Button>
        </div>
        <div v-show="checklistOpen" id="prepare-checklist" class="mt-3 space-y-3 border-t pt-3">
          <template v-for="g in counts.checklist" :key="g.key">
            <div v-if="g.items.length" class="space-y-1">
              <p class="text-sm font-semibold">{{ g.heading }} ({{ g.items.length }})</p>
              <p class="text-xs text-muted-foreground">{{ g.meaning }}</p>
              <ul class="list-disc space-y-0.5 pl-5 text-sm [overflow-wrap:anywhere]">
                <li v-for="(e, i) in g.items" :key="`${e.key}-${i}`" :class="e.otherWeek && 'font-medium text-warn-fg'" :data-other-week="e.otherWeek || undefined">{{ e.label }}: {{ e.why }}</li>
              </ul>
            </div>
          </template>
        </div>
      </div>

      <section aria-labelledby="prepare-sources-title" class="space-y-3 rounded-lg border p-4 sm:p-6" data-card="prepare_sources">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="prepare-sources-title" class="text-lg font-semibold"><span class="mr-2 tabular-nums">1</span>Source documents</h3>
          <p v-if="rows.length" class="text-sm text-muted-foreground tabular-nums">{{ rows.filter((r) => r.added).length }} of {{ rows.length }} added</p>
        </div>
        <p v-if="!rows.length" class="text-sm">{{ noDocumentsLine(steps ?? []) }}</p>
        <!-- Explicit roles: on a phone the rows are restyled as stacked blocks, and the roles keep them a table to a screen reader. -->
        <table v-else role="table" class="w-full text-sm max-sm:block">
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
              <td role="cell" class="py-2.5 pr-3 text-muted-foreground max-sm:block max-sm:p-0" :aria-busy="busy === `upload-${r.key}` || undefined">
                <UploadProgress v-if="busy === `upload-${r.key}`" :name="picked[r.key] ?? r.label" />
                <template v-else>
                  <!-- another week's file: the warning ink of a not-auto-verified item (--warn-fg, light and dark) -->
                  <p :class="r.warn && 'font-medium text-warn-fg'" :data-other-week="r.warn || undefined">{{ r.status }}</p>
                  <ul v-if="r.upload && r.files.length" class="mt-1 space-y-1" :aria-label="`Kept for ${r.label}`">
                    <li v-for="f in r.files" :key="f.storedName" class="flex flex-wrap items-center gap-2 text-xs text-foreground" data-kept-file>
                      <span class="font-mono [overflow-wrap:anywhere]">{{ f.name }}</span>
                      <Button
                        variant="outline"
                        size="sm"
                        class="min-h-11"
                        :disabled="busy !== null"
                        :aria-label="`Remove ${f.name} from ${r.label}`"
                        @click="removing = { label: r.label, file: f }"
                      >
                        <PhTrash weight="bold" data-icon="inline-start" aria-hidden="true" />
                        {{ busy === `remove-${f.storedName}` ? "Removing…" : "Remove" }}
                      </Button>
                    </li>
                  </ul>
                </template>
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
        <RedraftDialog
          :open="removing !== null"
          :title="`Remove ${removing?.file.name ?? 'this file'}?`"
          :notes="removing ? [`${removing.file.name} is taken out of this week’s inputs for ${removing.label}, which then counts it as not uploaded. Upload it again to put it back.`, 'Saved drafts, approved reviews and the history store are not changed.'] : []"
          confirm-label="Remove the file"
          @confirm="removeFile"
          @cancel="removing = null"
        />
      </section>

      <div v-if="formCall.problem.value" class="flex flex-wrap items-center gap-3" data-part-problem="form">
        <Notice tone="warn" role="alert" class="flex-1">The report inputs could not be read. {{ formCall.problem.value }}</Notice>
        <Button variant="outline" class="min-h-11" @click="readForm">Try again</Button>
      </div>
      <InputSteps
        v-if="steps"
        :key="`${section.slug} ${report.period}`"
        :steps="steps"
        :form="form"
        :week="week"
        :section="section.slug"
        :missing="counts.missing"
        :start="start"
        heading="Report inputs"
        :n="2"
        data-card="prepare_inputs"
        @form="(f) => (form = f)"
        @changed="done"
      >
        <template #step="{ step, next }">
          <!-- Focus of the Week: the topic, then the titles. Kept on this page and sent with the draft. -->
          <div v-if="step.kind === 'topic'" class="space-y-1.5">
            <label for="prepare-topic" class="block text-sm font-medium">This week’s topic</label>
            <input
              id="prepare-topic"
              v-model="topic"
              type="text"
              autocomplete="off"
              :aria-invalid="topicOver || undefined"
              aria-describedby="prepare-topic-hint prepare-topic-count"
              class="flex min-h-11 w-full rounded-md border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 aria-invalid:border-flag"
              @keydown.enter.prevent="next"
            />
            <p id="prepare-topic-hint" class="text-xs text-muted-foreground">Your editorial call. The tool collects research notes for the topic you give it; you write the sections.</p>
            <p id="prepare-topic-count" aria-live="polite" class="text-xs" :class="topicOver ? 'font-medium text-flag-fg' : 'text-muted-foreground'">
              <span class="tabular-nums">{{ topicLength(topic) }}</span> of {{ MAX_TOPIC }} characters.<template v-if="topicOver"> Please shorten the topic.</template>
            </p>
          </div>
          <div v-else-if="step.kind === 'titles'" class="space-y-1.5">
            <label for="prepare-titles" class="block text-sm font-medium">Section titles</label>
            <p id="prepare-titles-lines" class="text-xs text-muted-foreground">One per line.</p>
            <textarea
              id="prepare-titles"
              v-model="titles"
              rows="5"
              :aria-invalid="!!titlesError || undefined"
              aria-describedby="prepare-titles-lines prepare-titles-hint prepare-titles-count"
              class="w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 aria-invalid:border-flag"
            />
            <p id="prepare-titles-hint" class="text-xs text-muted-foreground">
              {{ bedrock ? "Required: the tool collects research notes for each title from its own verified sources." : "Optional here: left blank, the tool proposes four to six titles from the topic." }}
              A closing “Recommendations and Conclusion” title gets no notes.
            </p>
            <p id="prepare-titles-count" aria-live="polite" class="text-xs" :class="titlesError ? 'font-medium text-flag-fg' : 'text-muted-foreground'">
              <span class="tabular-nums">{{ sectionTitles(titles).length }}</span> of {{ MAX_SECTIONS }} titles, each at most {{ MAX_SECTION_TITLE }} characters.<template v-if="titlesError"> {{ titlesError.charAt(0).toUpperCase() + titlesError.slice(1) }}.</template>
            </p>
          </div>
          <!-- A Real Estate sector: the old start screen's own snip markup, from the one snip store on this page. -->
          <div v-else-if="step.kind === 'snips' && sectorOf(step.key)" class="space-y-3" data-snip>
            <Notice v-if="snips.error.value" role="alert" class="font-medium">{{ snips.error.value }}</Notice>
            <SnipSector :sec="sectorOf(step.key)!" :snips="snips" :week="week" :disabled="false" compact />
          </div>
          <!-- The fund table: the chat's own card, as it stands. -->
          <FundSnipCard v-else-if="step.kind === 'fund'" :week="week" :section="section.slug" @changed="done" />
          <SourcesPanel v-else-if="step.kind === 'sources'" :section="section" :report="report" :titles="titles" :disabled="false" @pieces="(p) => (pieces = p)" />
        </template>
      </InputSteps>

      <section aria-labelledby="prepare-draft-title" class="rounded-lg border p-4 sm:p-6" data-card="prepare_draft">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0 flex-1 basis-72 space-y-1">
            <h3 id="prepare-draft-title" class="text-lg font-semibold"><span class="mr-2 tabular-nums">3</span>Create draft</h3>
            <p class="text-sm text-muted-foreground">Draft this section using what’s in place. Anything still missing comes back as a named gap, never as invented text.</p>
            <p v-if="card.kind === 'blocked' || card.kind === 'none'" class="text-sm">{{ card.why }}</p>
            <p v-else-if="card.kind === 'running' || card.kind === 'queued'" class="text-sm">This section is being drafted. <template v-if="SHOW_CHAT"><RouterLink :to="conversationTo" :class="LINK">Open the conversation</RouterLink> to follow it.</template><RouterLink v-else :to="conversationTo" :class="LINK">Follow the draft</RouterLink></p>
            <RouterLink v-else-if="!SHOW_CHAT && hasDraftWork(section, drafting)" :to="conversationTo" :class="['inline-flex min-h-11 items-center text-sm', LINK]">Open the draft</RouterLink>
          </div>
          <div v-if="card.kind === 'ready' || card.kind === 'failed'" class="space-y-1 text-center max-sm:w-full">
            <Button class="min-h-11 px-6 max-sm:w-full" :aria-disabled="blocked || undefined" aria-describedby="prepare-draft-caption" @click="!blocked && create()">
              {{ opening || starting ? "Starting…" : "Create draft" }}<PhArrowRight weight="bold" data-icon="inline-end" aria-hidden="true" />
            </Button>
            <p id="prepare-draft-caption" class="text-xs text-muted-foreground" data-caption>{{ caption }}</p>
          </div>
        </div>
        <Notice v-if="openProblem || problem" role="alert" class="mt-3 font-medium">{{ openProblem || problem }}</Notice>
        <RedraftDialog :open="asking !== null" title="Draft this section?" :notes="asking ?? []" confirm-label="Draft anyway" @confirm="draft" @cancel="cancelled" />
      </section>

      <ExportBar rows @status="(st) => (exportStatus = st)" :period="report.period" :refresh-key="`${section.latest?.run_id ?? 0}-${section.latest?.decision ?? ''}`" @error="(m) => (exportProblem = m)" />
      <ExportNotices :status="exportStatus" :error="exportProblem" />
    </template>
  </div>
</template>
