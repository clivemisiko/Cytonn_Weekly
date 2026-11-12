<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { LINK } from "@/components/ui/button";
import * as api from "@/lib/api";
import { draftingFor, draftingList, draftingStatus, isLive, ownBusy, providerOff, reattachHref, useDraftingPoll, useLiveElapsed } from "@/lib/drafting";
import { elapsed, friendlyTime, weekRange } from "@/lib/format";
import { draftChartsNote } from "@/lib/charts";
import { redraftNotes } from "@/lib/redraft";
import type { snipCounts } from "@/lib/snips";
import { TITLES_REQUIRED, missingSourcesNote, piecesNothingFoundFor, piecesWithoutSources, usesSources } from "@/lib/sources";
import { shell, useShellRibbon } from "@/lib/shell";
import { MAX_SECTIONS, MAX_SECTION_TITLE, MAX_TOPIC, sectionsProblem, sectionTitles, topicLength } from "@/lib/topic";
import type { AppConfig, Drafting, Overview, ReportChoice, Review, SectionSummary, SourcePiece } from "@/lib/types";
import PageGrid from "@/components/nav/PageGrid.vue";
import AnalystPanel from "./analyst/AnalystPanel.vue";
import InputsPanel from "./InputsPanel.vue";
import Masthead from "./Masthead.vue";
import NotablePanel from "./NotablePanel.vue";
import Notice from "./Notice.vue";
import RedraftDialog from "./RedraftDialog.vue";
import SnipsPanel from "./SnipsPanel.vue";
import SourcesPanel from "./SourcesPanel.vue";

const USES_INPUTS = ["fixed_income", "equities"];

/**
 * One section's start: what a run does (the section's own steps, from the API), the report and period it is for, its
 * current saved review to resume, and the draft button. Focus of the Week also takes the analyst's topic; the tool
 * never picks it.
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
  /** Every draft the server reported when this screen was opened (running, queued, or a newest failure). */
  drafting: Drafting[];
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
const inputMissing = computed(() => props.section.needs_topic && !topic.value.trim());
// Counted as the API counts it (lib/topic.ts). Nothing is ever cut: an over-long topic stays whole and blocks the draft.
const topicCount = computed(() => topicLength(topic.value));
const topicOver = computed(() => props.section.needs_topic && topicCount.value > MAX_TOPIC);
// Focus of the Week's section titles, one per line, counted and refused as the API does (lib/topic.ts).
const sections = ref("");
const sectionCount = computed(() => sectionTitles(sections.value).length);
const sectionsError = computed(() => (props.section.needs_topic ? sectionsProblem(sections.value) : null));
// True from the click until the run view takes over (the start call answers at once).
const starting = ref(false);
const error = ref<{ message: string; lostConnection: boolean } | null>(null);
// The week's uploads changed (the analyst inputs form re-reads the workbook's values), and whether something typed on
// that form is not saved yet: a draft started then would not see it, so the draft button waits.
const uploads = ref(0);
const typedPending = ref(false);
const usesInputs = computed(() => props.report.type === "weekly" && !!props.week && USES_INPUTS.includes(props.section.slug));
// Digital Payments has no analyst form; its panel holds the optional workbook upload alone.
const showsInputs = computed(() => usesInputs.value || (props.report.type === "weekly" && !!props.week && props.section.slug === "digital_payments"));
// The Executive Summary calls no LLM: no API budget, no key needed, no draft slot.
const llm = computed(() => props.section.uses_provider);
const providerBlocked = computed(() => providerOff(llm.value, props.config));
// A Bedrock draft is written only from saved sources (the Sources panel); the tool searches for them when the draft starts.
// The weekly Real Estate is written from the analyst's snips instead: it has no Sources panel, no search and no "Add a source".
const snipsSection = computed(() => props.report.type === "weekly" && !!props.week && props.section.slug === "real_estate");
const snipCountsNow = ref<ReturnType<typeof snipCounts> | null>(null);
const bedrock = computed(() => usesSources(props.config, props.section) && !snipsSection.value);
const sourcePieces = ref<SourcePiece[] | null>(null);
const withoutSources = computed(() => (bedrock.value && sourcePieces.value ? piecesWithoutSources(sourcePieces.value) : []));
const nothingFound = computed(() => (bedrock.value && sourcePieces.value ? piecesNothingFoundFor(sourcePieces.value) : []));
// Bedrock has nothing to search, so a Focus needs its section titles typed: the API refuses a draft without them.
const titlesNeeded = computed(() => bedrock.value && props.section.needs_topic && sectionTitles(sections.value).length === 0);
const sectionsHint = computed(() =>
  bedrock.value
    ? "Enter custom section titles, one per line (e.g. Overview, Market Performance, Recommendations and Conclusion). The tool numbers them Section I, II, III… and each draws from its own verified sources below. End with a “Recommendations and Conclusion” part for the closing section."
    : "Leave blank and the tool proposes four to six titles from the topic (one model call). Typed titles are used exactly as typed and numbered Section I, II, III… by the tool; end with a \"Recommendations and Conclusion\" part for the closing section.",
);

// Only this section's own draft (running or queued) holds its Draft button; other sections drafting never do.
const serverDrafting = ref<Drafting | null>(draftingFor(props.drafting, props.section.slug, props.report));
let watched = isLive(serverDrafting.value);
function onServerOverview(next: Overview) {
  shell.setOverview(next); // the rail reads the same payload as this screen's poll
  serverDrafting.value = draftingFor(draftingList(next), props.section.slug, props.report);
  const wasMine = watched;
  watched = isLive(serverDrafting.value);
  if (wasMine && !watched) void props.onRecheck(); // offer what it saved
}
useDraftingPoll(() => (serverDrafting.value ? [serverDrafting.value] : []), onServerOverview, () => props.report, () => !starting.value);
const blocked = computed(() => ownBusy(llm.value, serverDrafting.value));
const queued = computed(() => serverDrafting.value?.state === "queued");
const seconds = useLiveElapsed(serverDrafting);
// This section's own draft is running (left and come back, a reload, or started in another tab): its run page shows the
// steps and the counter, so go there instead of offering a draft. Replace, so Back does not return to this screen.
const resume = computed(() => (llm.value && !starting.value ? reattachHref(serverDrafting.value, props.section.slug, props.report) : null));
watch(resume, (to) => to && void router.replace(to), { immediate: true });
const cannotDraft = computed(
  () =>
    starting.value || blocked.value || providerBlocked.value || inputMissing.value || topicOver.value || !!sectionsError.value || titlesNeeded.value || (usesInputs.value && typedPending.value),
);

// Drafting over a section that already has a review asks first (what happens to the earlier one), then drafts.
const confirming = ref(false);
const notes = computed(() => (props.saved ? redraftNotes(props.saved, props.report.type, props.section.requires_approved) : []));
// Fixed Income and Equities say first how many of their charts have no image; the analyst may draft anyway.
const chartNote = ref<string | null>(null);
async function start() {
  if (usesInputs.value && props.week) {
    try {
      chartNote.value = draftChartsNote((await api.getInputs(props.week)).charts ?? [], props.section.slug);
    } catch {
      chartNote.value = null; // a failed read never stops a draft
    }
    if (chartNote.value) return;
  }
  afterCharts();
}
// A Bedrock draft says first which pieces a search has already found nothing for; the analyst may draft anyway. With none, no question is asked.
const sourcesNote = ref<string | null>(null);
function afterCharts() {
  sourcesNote.value = missingSourcesNote(nothingFound.value);
  if (!sourcesNote.value) afterSources();
}
function afterSources() {
  if (props.saved) confirming.value = true;
  else void draft();
}
function chartsConfirmed() {
  chartNote.value = null;
  afterCharts();
}
function sourcesConfirmed() {
  sourcesNote.value = null;
  afterSources();
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
      sections: props.section.needs_topic && sections.value.trim() ? sections.value : undefined,
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
        onServerOverview(await api.getOverview(props.report)); // show that this section is already drafting or queued
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
    <Masthead wide :title="`${section.title}: analyst review`">
      <template v-if="!weekly" #meta><span class="font-mono">{{ report.period }}</span></template>
      {{ weekly ? "Draft this week’s section, check it, and review it here." : `Draft ${thisRun} section, check it, and review it here.` }}
    </Masthead>

    <!-- The panel is first in the page's order: what is uploaded and typed there is what the form and the draft button use.
         It is never folded (it holds the uploads' warnings) and, being tall, it does not stick. -->
    <p v-if="resume" role="status" class="mx-auto w-full max-w-275 px-4 py-8 text-sm sm:px-6">Opening the draft that is running…</p>
    <PageGrid v-else aside-title="Inputs and steps" hide-title aside-first wide-body :sticky="false">
      <div class="space-y-8">
        <AnalystPanel v-if="usesInputs && week" :key="`analyst-${week}`" :week="week" :section="section.slug" :disabled="starting" :refresh="uploads" @pending="(p) => (typedPending = p)" />
        <SnipsPanel v-if="snipsSection && week" :key="`snips-${week}`" :week="week" :disabled="starting" @counts="(c) => (snipCountsNow = c)" />
        <SourcesPanel v-if="bedrock" :section="section" :report="report" :titles="sections" :disabled="starting" @pieces="(p) => (sourcePieces = p)" />
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
                  ? "Or create a new draft. The existing review will remain safely saved in your archive."
                  : section.requires_approved
                    ? `Not composed ${forWhen} yet. It is built only from sections you have approved.`
                    : `No review ${forWhen} yet. Draft ${thisRun} ${section.title} section, check it, and review it here.`
              }}
            </p>

            <Notice v-if="providerBlocked" role="alert" class="font-medium">{{ config.provider_problem }} Drafting is off until then.</Notice>
            <Notice v-if="config.dev_mode && llm" role="alert" class="font-semibold">
              Development Mode Active (Local Model): Drafts generated in this mode are for testing purposes only and are not approved for publication.
            </Notice>
            <Notice v-if="llm && config.spends_api_budget && !config.provider_problem" tone="info">
              <template v-if="snipsSection">
                Drafting Engine: {{ config.provider }}. This action will query the AI model. Each sector is written only from its confirmed snips; the REIT prices come from the NSE Ibuka weekly PDF. Nothing is searched.
              </template>
              <template v-else-if="bedrock">
                Drafting Engine: {{ config.provider }}. This action will query the AI model and retrieve relevant source documents. Each piece is
                written only from its saved sources. You can add more at any time.
              </template>
              <template v-else>Drafting Engine: {{ config.provider }}. This action will query the AI model and search for relevant source materials.</template>
            </Notice>
            <Notice v-if="!llm" tone="info">
              Executive Summary synthesis: Content is compiled from your approved sections along with their verified sources and checked for consistency.
            </Notice>

            <!-- A draft already running on the server (started from another tab, or before this screen was opened). -->
            <template v-if="serverDrafting && isLive(serverDrafting) && !starting && llm">
              <Notice v-if="serverDrafting.stale" tone="warn" role="status">
                <span class="font-semibold">
                  This draft run appears to have stalled. This section has been drafting for
                  <span class="font-mono tabular-nums">{{ elapsed(seconds) }}</span></span
                >. Starting a new draft will replace it.
              </Notice>
              <Notice v-else tone="info" role="status">
                <span class="font-semibold">
                  {{ draftingStatus(serverDrafting) }}<template v-if="!queued"> (<span class="font-mono tabular-nums">{{ elapsed(seconds) }}</span
                  >, started {{ friendlyTime(serverDrafting.started_at) }})</template>.
                </span>
                {{
                  queued
                    ? "It starts by itself when a drafting seat is free."
                    : "It is saved when it finishes, and this screen then offers it for review."
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
                class="flex h-10 w-full rounded-md border border-input bg-card px-3 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-flag"
                @input="error = null"
                @keydown.enter="topicEnter"
              />
              <p id="focus-topic-hint" class="text-xs text-muted-foreground">
                Your editorial call. The tool researches and drafts the topic you give it, with a source for every claim.
              </p>
              <p id="focus-topic-count" class="text-xs" :class="topicOver ? 'font-medium text-flag-fg' : 'text-muted-foreground'">
                <span class="font-mono tabular-nums">{{ topicCount.toLocaleString() }}</span> of {{ MAX_TOPIC.toLocaleString() }} characters.
                <span v-if="topicOver" role="status">
                  Please shorten the topic by <span class="font-mono tabular-nums">{{ (topicCount - MAX_TOPIC).toLocaleString() }}</span>
                  {{ topicCount - MAX_TOPIC === 1 ? "character" : "characters" }} to proceed.
                </span>
              </p>
            </div>

            <div v-if="section.needs_topic" class="space-y-1">
              <label for="focus-sections" class="text-sm font-semibold">Sections (optional)</label>
              <Textarea
                id="focus-sections"
                v-model="sections"
                name="sections"
                rows="5"
                :disabled="starting"
                :placeholder="'One title per line, e.g.\nOverview of the market\nYields and pricing\nRecommendations and Conclusion'"
                :aria-invalid="!!sectionsError || undefined"
                aria-describedby="focus-sections-hint focus-sections-count"
                class="min-h-28 py-2"
              />
              <p id="focus-sections-hint" class="text-xs text-muted-foreground">{{ sectionsHint }}</p>
              <p v-if="titlesNeeded" role="status" class="text-xs font-medium text-warn-fg">{{ TITLES_REQUIRED }}</p>
              <p id="focus-sections-count" class="text-xs" :class="sectionsError ? 'font-medium text-flag-fg' : 'text-muted-foreground'">
                <span class="font-mono tabular-nums">{{ sectionCount }}</span> of {{ MAX_SECTIONS }} sections, each at most {{ MAX_SECTION_TITLE }} characters.
                <span v-if="sectionsError" role="status">{{ sectionsError.charAt(0).toUpperCase() + sectionsError.slice(1) }}. Please shorten or remove the indicated section title to proceed.</span>
              </p>
            </div>

            <!-- Pre-draft Readiness Checklist -->
            <div class="rounded-xl border border-border bg-muted/40 p-3.5 space-y-2 text-xs">
              <p class="font-semibold text-foreground flex items-center justify-between">
                <span>Draft readiness checklist</span>
                <span :class="cannotDraft ? 'text-warn-fg font-medium' : 'text-ok-fg font-semibold'">
                  {{ cannotDraft ? "Prerequisites pending" : "Ready to draft" }}
                </span>
              </p>
              <ul class="space-y-1.5 text-muted-foreground">
                <li class="flex items-center gap-2">
                  <span v-if="!providerBlocked" class="flex size-4 items-center justify-center rounded-full bg-ok/20 font-bold text-ok-fg text-[10px]">✓</span>
                  <span v-else class="flex size-4 items-center justify-center rounded-full bg-flag/20 font-bold text-flag-fg text-[10px]">✗</span>
                  <span>AI Engine: {{ providerBlocked ? config.provider_problem : (llm ? `${config.provider} active` : 'Internal synthesis (no external LLM)') }}</span>
                </li>
                <li v-if="section.needs_topic" class="flex items-center gap-2">
                  <span v-if="topic.trim() && !topicOver" class="flex size-4 items-center justify-center rounded-full bg-ok/20 font-bold text-ok-fg text-[10px]">✓</span>
                  <span v-else class="flex size-4 items-center justify-center rounded-full bg-warn/20 font-bold text-warn-fg text-[10px]">!</span>
                  <span>Focus topic: {{ topic.trim() ? (topicOver ? 'Exceeds limit' : 'Provided') : 'Topic required above' }}</span>
                </li>
                <li v-if="usesInputs" class="flex items-center gap-2">
                  <span v-if="!typedPending" class="flex size-4 items-center justify-center rounded-full bg-ok/20 font-bold text-ok-fg text-[10px]">✓</span>
                  <span v-else class="flex size-4 items-center justify-center rounded-full bg-warn/20 font-bold text-warn-fg text-[10px]">!</span>
                  <span>Analyst form: {{ typedPending ? 'Unsaved or unconfirmed inputs in form' : 'Inputs confirmed' }}</span>
                </li>
                <li v-if="snipsSection && snipCountsNow" class="flex items-center gap-2">
                  <span v-if="snipCountsNow.confirmed && !snipCountsNow.unconfirmed" class="flex size-4 items-center justify-center rounded-full bg-ok/20 font-bold text-ok-fg text-[10px]">✓</span>
                  <span v-else class="flex size-4 items-center justify-center rounded-full bg-warn/20 font-bold text-warn-fg text-[10px]">!</span>
                  <span>Snips: {{ snipCountsNow.confirmed }} confirmed, {{ snipCountsNow.unconfirmed }} unconfirmed (not used){{ snipCountsNow.without.length ? `; not included: ${snipCountsNow.without.join(", ")}` : "" }}</span>
                </li>
                <li v-if="bedrock && sourcePieces" class="flex items-center gap-2">
                  <span v-if="!titlesNeeded && !withoutSources.length" class="flex size-4 items-center justify-center rounded-full bg-ok/20 font-bold text-ok-fg text-[10px]">✓</span>
                  <span v-else-if="!titlesNeeded && nothingFound.length" class="flex size-4 items-center justify-center rounded-full bg-warn/20 font-bold text-warn-fg text-[10px]">!</span>
                  <span v-else class="flex size-4 items-center justify-center rounded-full bg-muted font-bold text-muted-foreground text-[10px]">·</span>
                  <span>Sources: {{ titlesNeeded ? "add section titles to see source requirements" : !withoutSources.length ? "every piece has at least one" : nothingFound.length ? `a search found nothing for ${nothingFound.length} of ${sourcePieces.length} pieces` : "found automatically when you draft" }}</span>
                </li>
                <li v-if="blocked" class="flex items-center gap-2 text-warn-fg font-medium">
                  <span class="flex size-4 items-center justify-center rounded-full bg-warn/20 font-bold text-[10px]">⏳</span>
                  <span>{{ serverDrafting ? draftingStatus(serverDrafting) : "Being drafted now" }}</span>
                </li>
              </ul>
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
              You have unsaved changes or unconfirmed suggestions in Weekly Analyst Inputs. Please save or confirm all pending values before drafting.
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
            <RedraftDialog
              :open="sourcesNote !== null"
              title="Some pieces have no sources"
              :notes="sourcesNote ? [sourcesNote, 'Add a link or paste text for them and draft again, or draft anyway and fill them in afterwards.'] : []"
              confirm-label="Draft anyway"
              cancel-label="Go back"
              @confirm="sourcesConfirmed"
              @cancel="sourcesNote = null"
            />
            <RedraftDialog
              :open="chartNote !== null"
              title="Some charts have no image"
              :notes="chartNote ? [chartNote] : []"
              confirm-label="Draft anyway"
              cancel-label="Go back"
              @confirm="chartsConfirmed"
              @cancel="chartNote = null"
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
        <InputsPanel v-if="showsInputs && week" :key="week" :week="week" :section="section.slug" :disabled="starting" @week="(w) => emit('week', w)" @change="uploads++" />
        <div class="space-y-6" :class="showsInputs && week && 'border-t pt-6'">
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
