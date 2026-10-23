<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { LINK } from "@/components/ui/button";
import * as api from "@/lib/api";
import { isDraftingThis, providerOff, slotTaken, useDraftingPoll, useLiveElapsed } from "@/lib/drafting";
import { elapsed, friendlyTime, weekRange } from "@/lib/format";
import { redraftNotes } from "@/lib/redraft";
import { shell, useShellRibbon } from "@/lib/shell";
import { MAX_TOPIC, topicLength } from "@/lib/topic";
import type { AppConfig, Drafting, Overview, ReportChoice, Review, SectionSummary } from "@/lib/types";
import PageGrid from "@/components/nav/PageGrid.vue";
import AnalystPanel from "./analyst/AnalystPanel.vue";
import InputsPanel from "./InputsPanel.vue";
import Masthead from "./Masthead.vue";
import NotablePanel from "./NotablePanel.vue";
import Notice from "./Notice.vue";
import RedraftDialog from "./RedraftDialog.vue";

/** The weekly sections worked out from the week's uploaded inputs. */
const USES_INPUTS = ["fixed_income", "equities"];
const MAX_TEXT = 10_000;

/**
 * One section's start: what a run does (the section's own steps, from the API), the report and period it is for, its
 * current saved review to resume, and the draft button. Focus of the Week also takes the coordinator's topic and
 * Company Updates their text; the tool never picks the one or writes the other.
 *
 * The draft button starts a run (POST /api/runs) and goes to its run view (/runs/{run_id}), which shows the draft's
 * real steps as they happen and then hands over to the review. Nothing here waits for the draft itself.
 */
const props = defineProps<{
  section: SectionSummary;
  config: AppConfig;
  /** The report and period this section is drafted for (chosen on the overview). */
  report: ReportChoice;
  saved: Review | null;
  /** The draft running on the server when this screen was opened, if any. */
  drafting: Drafting | null;
  /** Weekly only: the Friday the report week ends on (the period's, or the latest Friday). */
  week: string | null;
  onRecheck: () => Promise<void>;
}>();
const emit = defineEmits<{
  /** Choose another report week; the report on screen changes with it. */
  week: [weekEnding: string];
  open: [review: Review];
  home: [];
}>();

const router = useRouter();
useShellRibbon(() => (props.config.dev_mode ? props.config.dev_mode_label : null)); // the shell draws it under the top bar
const weekly = computed(() => props.report.type === "weekly" && !props.report.period);
const thisRun = computed(() => (weekly.value ? "this week’s" : `the ${props.report.period}`));
const topic = ref("");
const text = ref("");
const inputMissing = computed(() => (props.section.needs_topic && !topic.value.trim()) || (props.section.needs_text && !text.value.trim()));
// Counted as the API counts it (lib/topic.ts). Nothing is ever cut: an over-long topic stays whole and blocks the draft.
const topicCount = computed(() => topicLength(topic.value));
const topicOver = computed(() => props.section.needs_topic && topicCount.value > MAX_TOPIC);
// True from the click until the run view takes over (the start call answers at once).
const starting = ref(false);
const error = ref<{ message: string; lostConnection: boolean } | null>(null);
// The week's uploads changed (the analyst inputs form re-reads the workbook's values), and whether something typed on
// that form is not saved yet: a draft started then would not see it, so the draft button waits.
const uploads = ref(0);
const typedPending = ref(false);
const usesInputs = computed(() => props.report.type === "weekly" && !!props.week && USES_INPUTS.includes(props.section.slug));
// Company Updates and the Executive Summary call no LLM: no API budget, no key needed, no draft slot.
const llm = computed(() => props.section.uses_provider);
const providerBlocked = computed(() => providerOff(llm.value, props.config));

// A draft already running on the server (this section's or another's) blocks this one until it finishes.
const serverDrafting = ref<Drafting | null>(props.drafting);
let watched = isDraftingThis(props.drafting, props.section.slug, props.report);
function onServerOverview(next: Overview) {
  shell.setOverview(next); // the rail reads the same payload as this screen's poll
  serverDrafting.value = next.drafting;
  const wasMine = watched;
  watched = isDraftingThis(next.drafting, props.section.slug, props.report);
  if (wasMine && !watched) void props.onRecheck(); // offer what it saved
}
useDraftingPoll(serverDrafting, onServerOverview, () => props.report, () => !starting.value);
const blocked = computed(() => slotTaken(llm.value, serverDrafting.value));
const mine = computed(() => isDraftingThis(serverDrafting.value, props.section.slug, props.report));
const seconds = useLiveElapsed(serverDrafting);
const cannotDraft = computed(
  () => starting.value || blocked.value || providerBlocked.value || inputMissing.value || topicOver.value || (usesInputs.value && typedPending.value),
);

// Drafting over a section that already has a review asks first (what happens to the earlier one), then drafts.
const confirming = ref(false);
const notes = computed(() => (props.saved ? redraftNotes(props.saved, props.report.type, props.section.requires_approved) : []));
function start() {
  if (props.saved) confirming.value = true;
  else void draft();
}
function confirmed() {
  confirming.value = false;
  void draft();
}

async function draft() {
  error.value = null;
  starting.value = true;
  try {
    const { run_id } = await api.startRun(props.section.slug, props.report, {
      topic: props.section.needs_topic ? topic.value.trim() : undefined,
      text: props.section.needs_text ? text.value.trim() : undefined,
      provider: llm.value ? props.config.provider : undefined,
    });
    void router.push(`/runs/${run_id}`);
  } catch (err) {
    const e = err as api.ApiError;
    // No HTTP status means the answer never arrived (timeout, dropped connection): the run may have started
    // all the same, and it saves its draft when it finishes. A 409 means a draft is already running.
    error.value = { message: e.message, lostConnection: llm.value && (e.status === null || e.status === 409) };
    starting.value = false;
    if (llm.value && e.status === 409) {
      try {
        onServerOverview(await api.getOverview(props.report)); // show which draft holds the slot, and watch it finish
      } catch {
        /* the error above already says a draft is running */
      }
    }
  }
}

async function recheck() {
  error.value = null;
  await props.onRecheck();
}

function topicEnter() {
  if (!inputMissing.value && !topicOver.value && !starting.value && !blocked.value && !providerBlocked.value) start();
}

const items = computed(() => props.saved?.review_items ?? []);
const resolved = computed(() => items.value.filter((i) => i.resolution !== null).length);
const draftLabel = computed(() =>
  starting.value
    ? "Starting…"
    : props.section.needs_text
      ? "Save your text as the section"
      : props.section.requires_approved
        ? `Compose ${thisRun.value} summary`
        : `Draft ${thisRun.value} section`,
);
const forWhen = computed(() => (weekly.value ? "this week" : `for ${props.report.period}`));
const lists = computed(() => [
  { title: "In the real report", items: props.section.subsections, note: "" },
  {
    title: "Charts to add by hand",
    items: props.section.charts,
    note: "The real issue carries these charts. The tool does not draw them; the review screen lists them again as a checklist.",
  },
]);
</script>

<template>
  <div>
    <Masthead wide :title="`${section.title}: coordinator review`">
      <template v-if="!weekly" #meta><span class="font-mono">{{ report.period }}</span></template>
      {{ weekly ? "Draft this week’s section, check it, and review it here." : `Draft ${thisRun} section, check it, and review it here.` }}
    </Masthead>

    <!-- The panel is first in the page's order: what is uploaded and typed there is what the form and the draft button use.
         It is never folded (it holds the uploads' warnings) and, being tall, it does not stick. -->
    <PageGrid aside-title="Inputs and steps" hide-title aside-first wide-body :sticky="false">
      <div class="space-y-8">
        <AnalystPanel v-if="usesInputs && week" :key="`analyst-${week}`" :week="week" :section="section.slug" :disabled="starting" :refresh="uploads" @pending="(p) => (typedPending = p)" />
        <section aria-labelledby="start-title" class="space-y-6 rounded-lg border border-t-[3px] border-t-primary bg-card p-6">
          <h2 id="start-title" class="sr-only">Start or resume a review</h2>

          <div v-if="!weekly" class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b pb-4 text-sm">
            <p>
              <span class="eyebrow mr-2">Report</span>
              <span class="font-semibold">{{ report.period }}</span>
            </p>
            <button type="button" :class="['text-sm', LINK]" @click="emit('home')">Change report</button>
          </div>

          <div v-if="saved" class="space-y-3 border-b pb-6">
            <template v-if="saved.decision === null">
              <p class="text-sm">
                {{ weekly ? "This week’s" : `The ${report.period}` }} review is in progress (run {{ saved.run_id }},
                {{ weekly ? "report week" : "period" }} {{ weekRange(saved.section.week_start, saved.section.week_end) }}):
                <span class="font-mono">{{ resolved }}</span> of <span class="font-mono">{{ items.length }}</span> items resolved.
                Resuming it does not re-run the draft.
              </p>
              <div class="h-2 overflow-hidden rounded-full bg-border" aria-hidden="true">
                <div class="h-full rounded-full bg-foreground" :style="{ width: `${items.length ? (resolved / items.length) * 100 : 0}%` }" />
              </div>
            </template>
            <p v-else class="text-sm">
              {{ weekly ? "This week’s" : `The ${report.period}` }} review (run {{ saved.run_id }}) was {{ saved.decision
              }}{{ saved.decided_at ? ` on ${friendlyTime(saved.decided_at)}` : "" }}.
            </p>
            <Button size="lg" :variant="saved.decision === null ? 'default' : 'outline'" :disabled="starting" @click="emit('open', saved)">
              {{ saved.decision === null ? "Resume this review" : "View it" }}
            </Button>
          </div>

          <div data-attention="start-draft" class="space-y-3">
            <p class="text-sm">
              {{
                saved
                  ? "Or start over with a new draft. The saved review stays in the database either way."
                  : section.needs_text
                    ? `No ${section.title} saved ${forWhen} yet. Paste the text below.`
                    : section.requires_approved
                      ? `Not composed ${forWhen} yet. It is built only from sections you have approved.`
                      : `No review ${forWhen} yet. Draft ${thisRun} ${section.title} section, check it, and review it here.`
              }}
            </p>

            <Notice v-if="providerBlocked" role="alert" class="font-medium">{{ config.provider_problem }} Drafting is off until then.</Notice>
            <Notice v-if="config.dev_mode && llm" role="alert" class="font-semibold">
              CYTONN_LLM_PROVIDER=local: DEV MODE. Drafts from the local model are NOT FOR PUBLICATION.
            </Notice>
            <Notice v-if="llm && config.spends_api_budget && !config.provider_problem" tone="info">
              Drafting provider: {{ config.provider }}. A run spends real API budget (web search and tokens).
            </Notice>
            <Notice v-if="!llm" tone="info">
              {{
                section.needs_text
                  ? "Nothing is searched or drafted: your text is carried as written and listed once for you to accept."
                  : "Nothing is searched or drafted: each approved section’s lead piece is carried with its sources and checked again."
              }}
            </Notice>

            <!-- A draft already running on the server (started from another tab, or before this screen was opened). -->
            <template v-if="serverDrafting && !starting && llm">
              <Notice v-if="serverDrafting.stale" tone="warn" role="status">
                <span class="font-semibold">
                  {{ mine ? "This section" : serverDrafting.title }} has been drafting for
                  <span class="font-mono tabular-nums">{{ elapsed(seconds) }}</span></span
                >, longer than any healthy draft takes, and looks stuck. Starting a draft replaces it; its result will be discarded.
              </Notice>
              <Notice v-else tone="info" role="status">
                <span class="font-semibold">
                  {{ mine ? "This section is" : `${serverDrafting.title} is` }} drafting now (<span class="font-mono tabular-nums">{{ elapsed(seconds) }}</span
                  >, started {{ friendlyTime(serverDrafting.started_at) }}).
                </span>
                {{
                  mine
                    ? "It is saved when it finishes, and this screen then offers it for review."
                    : "Only one draft runs at a time, across every section; drafting here unlocks when it finishes."
                }}
              </Notice>
            </template>

            <div v-if="section.needs_topic" class="space-y-1">
              <label for="focus-topic" class="text-sm font-semibold">This week’s topic</label>
              <input
                id="focus-topic"
                v-model="topic"
                name="topic"
                type="text"
                autocomplete="off"
                :disabled="starting"
                placeholder="e.g. Sub-Saharan Africa Eurobonds performance…"
                :aria-invalid="topicOver || undefined"
                aria-describedby="focus-topic-hint focus-topic-count"
                class="flex h-10 w-full rounded-md border border-input bg-card px-3 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-flag md:text-sm"
                @input="error = null"
                @keydown.enter="topicEnter"
              />
              <p id="focus-topic-hint" class="text-xs text-muted-foreground">
                Your editorial call. The tool researches and drafts the topic you give it, with a source for every claim.
              </p>
              <p id="focus-topic-count" class="text-xs" :class="topicOver ? 'font-medium text-flag-fg' : 'text-muted-foreground'">
                <span class="font-mono tabular-nums">{{ topicCount.toLocaleString() }}</span> of {{ MAX_TOPIC.toLocaleString() }} characters.
                <span v-if="topicOver" role="status">
                  Over the limit by <span class="font-mono tabular-nums">{{ (topicCount - MAX_TOPIC).toLocaleString() }}</span>
                  {{ topicCount - MAX_TOPIC === 1 ? "character" : "characters" }}. Shorten it to submit.
                </span>
              </p>
            </div>

            <div v-if="section.needs_text" class="space-y-1">
              <label for="supplied-text" class="text-sm font-semibold">Your {{ section.title }} text</label>
              <Textarea
                id="supplied-text"
                v-model="text"
                name="text"
                rows="8"
                :maxlength="MAX_TEXT"
                :disabled="starting"
                :placeholder="'Investment Updates:\n…\n\nHospitality Updates:\n…'"
                aria-describedby="supplied-text-hint"
                class="min-h-40 py-2"
              />
              <p id="supplied-text-hint" class="text-xs text-muted-foreground">
                Cytonn’s own copy, as the real issue prints it under
                {{ section.subsections.map((h) => h.replace(/:$/, "")).join(" and ") || "this section" }}. Markdown links work.
                <span class="font-mono tabular-nums">{{ text.length.toLocaleString() }}</span> of {{ MAX_TEXT.toLocaleString() }} characters.
              </p>
            </div>

            <!-- A long period ("Draft the Week ending 2026-10-09 section") wraps on a phone instead of widening the page. -->
            <Button
              size="lg"
              :variant="saved ? 'outline' : 'default'"
              :disabled="cannotDraft"
              :aria-describedby="usesInputs && typedPending ? 'typed-pending' : undefined"
              class="h-auto min-h-10 max-w-full py-2 whitespace-normal"
              @click="start"
            >
              {{ draftLabel }}
            </Button>
            <p v-if="usesInputs && typedPending" id="typed-pending" role="status" class="text-xs font-medium text-warn-fg">
              Something under “Weekly analyst inputs” is not saved yet, or was carried or suggested and still needs
              confirming. Finish it there before drafting.
            </p>

            <div v-if="error" class="rise-in space-y-2">
              <Notice role="alert" data-problem class="font-medium">{{ error.message }}</Notice>
              <Button v-if="error.lostConnection" variant="outline" @click="recheck">Check for a saved draft</Button>
            </div>

            <RedraftDialog
              :open="confirming"
              :title="`Draft ${section.title} again?`"
              :notes="notes"
              confirm-label="Draft again"
              @confirm="confirmed"
              @cancel="confirming = false"
            />
          </div>
        </section>
        <!-- The weekly report's analyst worklist: suggestions with their working, never added to the draft. -->
        <NotablePanel
          v-if="report.type === 'weekly' && week"
          :key="`notable-${section.slug}-${week}`"
          :section="section.slug"
          :section-title="section.title"
          :week="week"
        />
      </div>

      <template #aside>
        <InputsPanel v-if="usesInputs && week" :key="week" :week="week" :disabled="starting" @week="(w) => emit('week', w)" @change="uploads++" />
        <div class="space-y-6" :class="usesInputs && week && 'border-t pt-6'">
          <section aria-labelledby="flow-title">
            <h2 id="flow-title" class="pb-4 text-lg font-semibold">What a run does</h2>
            <ol>
              <li
                v-for="(step, i) in section.steps"
                :key="step.title"
                class="relative flex gap-4 pb-6 last:pb-0 not-last:before:absolute not-last:before:top-7 not-last:before:bottom-1 not-last:before:left-3 not-last:before:w-px not-last:before:bg-input"
              >
                <span
                  class="relative z-10 grid size-6 shrink-0 place-items-center rounded-sm border font-mono text-xs font-semibold"
                  :class="i === section.steps.length - 1 ? 'border-foreground bg-foreground text-background' : 'border-input bg-card'"
                >
                  {{ i + 1 }}
                </span>
                <div>
                  <p class="text-sm font-semibold">{{ step.title }}</p>
                  <p class="text-sm text-muted-foreground">{{ step.body }}</p>
                </div>
              </li>
            </ol>
          </section>
          <!-- Short lists from the real issue (its own headings, its charts), shown beside the run's steps. -->
          <template v-for="list in lists" :key="list.title">
            <section v-if="list.items.length" class="space-y-2 border-t pt-6">
              <h3 class="eyebrow">{{ list.title }}</h3>
              <p v-if="list.note" class="text-xs text-muted-foreground">{{ list.note }}</p>
              <ul class="list-disc space-y-1 pl-5 text-sm marker:text-input">
                <li v-for="s in list.items" :key="s">{{ s }}</li>
              </ul>
            </section>
          </template>
        </div>
      </template>
    </PageGrid>
  </div>
</template>
