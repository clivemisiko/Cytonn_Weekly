<script setup lang="ts">
import { PhCaretRight, PhPauseCircle, PhUser } from "@phosphor-icons/vue";
import { computed, nextTick, onUnmounted, ref, shallowRef, useTemplateRef, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import CytonnMark from "@/components/brand/CytonnMark.vue";
import FullView from "@/components/chat/FullView.vue";
import LiveCards from "@/components/chat/LiveCards.vue";
import PreparePage from "@/components/chat/PreparePage.vue";
import ReadinessCard from "@/components/chat/ReadinessCard.vue";
import ReviewSummaryCard from "@/components/chat/ReviewSummaryCard.vue";
import PageGrid from "@/components/nav/PageGrid.vue";
import ActivityPanel from "@/components/review/ActivityPanel.vue";
import DraftingBanner from "@/components/review/DraftingBanner.vue";
import ExportBar from "@/components/review/ExportBar.vue";
import ExportNotices from "@/components/review/ExportNotices.vue";
import Masthead from "@/components/review/Masthead.vue";
import SectionRow from "@/components/review/SectionRow.vue";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { FIELD, LINK } from "@/components/ui/button";
import * as api from "@/lib/api";
import { type ChatCard, composerOff, createConversation, statusLine, toolLine } from "@/lib/chat";
import { PREPARE_SECTIONS, hasDraftWork, openView, parseReadiness, parseReviewSnapshot } from "@/lib/chatcards";
import { attentionList, draftAgainOff, draftingFor, draftingList, isLive, reportCounts, stateTally, useDraftingPoll } from "@/lib/drafting";
import { SHOW_CHAT } from "@/lib/features";
import { friendlyDate } from "@/lib/format";
import { BACK_NONE, type BackTarget, useBack } from "@/lib/nav";
import { APPROVED_BANNER, fullyApproved, openingWeek, weekChoiceLabel } from "@/lib/previous";
import { screenHref } from "@/lib/run";
import { railState, shell, useShellActions, useShellHere, useShellRibbon } from "@/lib/shell";
import type { AppConfig, ExportStatus, Overview, ReportChoice, WeekChoice } from "@/lib/types";

const route = useRoute();
const router = useRouter();
const SECTION_BTN = "h-11 rounded-sm border border-transparent bg-cw-chip px-4 font-normal text-foreground hover:bg-cw-chip hover:border-input aria-[current=true]:!border-cw-button aria-[current=true]:!bg-cw-bubble aria-[current=true]:font-semibold aria-[current=true]:text-cw-selected-fg";
const first = (v: unknown) => (Array.isArray(v) ? String(v[0] ?? "") : typeof v === "string" ? v : "");
const START_BTN = "h-12 w-full rounded-xl bg-cw-button font-semibold text-cw-button-fg hover:bg-cw-button hover:opacity-90";
const WEEK = /^Week ending \d{4}-\d{2}-\d{2}$/;

const config = shallowRef<AppConfig | null>(null);
const choices = shallowRef<WeekChoice[]>([]);
const defaultPeriod = ref("");
const overview = shallowRef<Overview | null>(null);
const problem = ref<string | null>(null);
const loading = ref(true);
const full = ref<{ reviewId: number; index: number | null } | null>(null); // the aside's read-only view; declared before load() runs

const convo = createConversation(api.chatApi);
const { job, messages, notice, lost, sending } = convo;
onUnmounted(convo.stop);

const period = computed(() => (WEEK.test(first(route.query.period)) ? first(route.query.period) : defaultPeriod.value));
const slug = computed(() => first(route.query.section) || null);
const report = computed<ReportChoice>(() => ({ type: "weekly", period: period.value, kind: null }));
const sections = computed(() => overview.value?.sections ?? []);
const current = computed(() => sections.value.find((s) => s.slug === slug.value) ?? null);
const weekOptions = computed(() => {
  const list = choices.value.map((c) => ({ period: c.period, label: weekChoiceLabel(c) }));
  const p = period.value;
  return p && !list.some((o) => o.period === p) ? [{ period: p, label: friendlyDate(p.slice("Week ending ".length)) }, ...list] : list;
});
// A section in PREPARE_SECTIONS opens on the prepare page while it has no draft; `view` in the address overrides it, so a link can
// open the conversation of a section with no draft, or the prepare page of one that has a draft.
const view = computed(() => first(route.query.view));
const state = computed(() => (overview.value && current.value ? railState(overview.value, current.value, report.value) : null));
const prepares = computed(() => !!current.value && PREPARE_SECTIONS.includes(current.value.slug));
const viewTo = (v: "prepare" | "conversation") => `/chat?${new URLSearchParams({ period: period.value, section: slug.value ?? "", view: v }).toString()}`;
const drafting = computed(() => (overview.value && current.value ? draftingFor(draftingList(overview.value), current.value.slug, report.value) : null));
const work = computed(() => !!current.value && hasDraftWork(current.value, drafting.value));
const preparing = computed(
  () => openView({ showChat: SHOW_CHAT, prepares: prepares.value, view: view.value, state: state.value, work: work.value }) === "prepare",
);

// The hidden page a chat button opens (the inputs form, the snips and sources, the Focus topic); there it shows "Back to chat".
const status = computed(() => statusLine(job.value));
const off = computed(() => composerOff(job.value, config.value, sending.value));
const used = computed(() => (job.value ? job.value.input_tokens + job.value.output_tokens : 0));

function choose(next: string | null) {
  full.value = null;
  void router.push({ path: "/chat", query: { period: period.value, ...(next ? { section: next } : {}) } });
}
/** "Whole report" opens the first section in the issue's order: each section is its own conversation. */
const wholeReport = () => choose(sections.value.find((s) => s.available)?.slug ?? null);
function chooseWeek(event: Event) {
  void router.replace({ path: "/chat", query: { ...route.query, period: (event.target as HTMLSelectElement).value } });
}

async function load() {
  loading.value = true;
  problem.value = null;
  full.value = null;
  try {
    if (!config.value) {
      const [c, weeks] = await Promise.all([api.getConfig(), api.getPreviousWeeks()]);
      config.value = c;
      shell.config.value = c;
      choices.value = weeks.choices ?? [];
      // Settled before the overview below is read, so the Week select never shows one week then another.
      if (!WEEK.test(first(route.query.period))) defaultPeriod.value = await openingWeek(weeks, () => api.getOverview());
    }
    overview.value = await api.getOverview(report.value);
    shell.setOverview(overview.value); // the rail takes the same payload
    // The chat hidden, a conversation view with no draft card would show only its back link: the address says prepare instead.
    if (!SHOW_CHAT && view.value === "conversation" && preparing.value) return void router.replace(viewTo("prepare"));
    const wanted = slug.value;
    // The prepare page opens no conversation: it reads the section's readiness on its own.
    if (wanted && !preparing.value && overview.value.sections.some((s) => s.slug === wanted && s.available)) await convo.open(wanted, period.value);
    else convo.stop();
  } catch (err) {
    problem.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}
watch(() => `${first(route.query.section)} ${first(route.query.period)} ${first(route.query.view)}`, load, { immediate: true });

// After any button on a card: the rail and the overview are read again, so neither shows an old state, and the cards read the server again.
const tick = ref(0);
async function changed() {
  shell.invalidate();
  tick.value++;
  try {
    overview.value = await api.getOverview(report.value);
    shell.setOverview(overview.value);
  } catch {
    /* the rail stays unknown rather than showing what may be old */
  }
}

// The aside with no section open: the report's figures, what needs the analyst, each section's own action and the export.
const ROW =
  "flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors duration-150 hover:bg-card focus-visible:ring-2 focus-visible:ring-ring";
const figures = computed<[string, number, string, string][]>(() => {
  if (!overview.value) return [];
  const c = reportCounts(overview.value);
  const all = sections.value.length;
  return [
    ["Approved", c.approved, ` / ${all}`, all && c.approved === all ? "text-ok-fg" : ""],
    ["In review", c.inReview, "", ""],
    ["Flagged", c.flagged, "", c.flagged > 0 ? "text-flag-fg" : ""],
    ["Drafting", c.drafting, "", ""],
  ];
});
const tally = computed(() => (overview.value ? stateTally(overview.value) : []));
const ATTENTION_SHOWN = 4;
const attention = computed(() => (overview.value ? attentionList(overview.value, report.value).slice(0, ATTENTION_SHOWN) : []));
// A section card's button goes where it went on the overview: its current review, else its start screen.
function openScreen(slug: string, resume: boolean) {
  const run = sections.value.find((s) => s.slug === slug)?.latest;
  void router.push(screenHref(report.value, resume && run ? { review: run.run_id } : { section: slug }));
}
const exportStatus = shallowRef<ExportStatus | null>(null);
const exportProblem = ref<string | null>(null);
// While a draft runs, the figures and states are read again every few seconds, as the overview did.
useDraftingPoll(
  () => (overview.value ? draftingList(overview.value) : []),
  (next) => {
    overview.value = next;
    shell.setOverview(next);
  },
  () => report.value,
  () => !current.value,
);

const openFull = (reviewId: number, index?: number | null) => (full.value = { reviewId, index: index ?? null });

// A saved card is read into its own shape here, once; one that is not as expected is shown by its name only.
const rows = computed(() =>
  messages.value.map((m) => ({
    m,
    cards: (m.cards ?? []).map((c: ChatCard) => {
      if (c.type === "readiness") return { type: c.type, readiness: parseReadiness(c.data) } as const;
      if (c.type === "review_summary") return { type: c.type, snapshot: parseReviewSnapshot(c) } as const;
      return { type: c.type } as const;
    }),
  })),
);

const draft = ref("");
async function submit() {
  if (off.value || !draft.value.trim()) return;
  if (await convo.send(draft.value)) draft.value = "";
}

const end = useTemplateRef<HTMLElement>("end");
watch(
  () => messages.value.length,
  async () => {
    await nextTick();
    end.value?.scrollIntoView({ block: "end", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  },
);

useShellRibbon(() => (config.value?.dev_mode ? config.value.dev_mode_label : null));
useShellHere(() => (slug.value ? { view: "section", slug: slug.value } : null));
useShellActions({ openSection: choose });
useBack((): BackTarget => (slug.value ? { kind: "go", to: "the section list", go: () => choose(null) } : BACK_NONE));
</script>

<template>
  <main id="main" tabindex="-1" class="cw-skin min-h-[calc(100dvh-var(--topbar-h))] bg-cw-page">
    <Masthead v-if="current" wide title="Chat" class="sr-only" />
    <header v-else class="px-4 pt-8 sm:px-6 min-[1100px]:px-10">
      <h1 class="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">Let's get this week's report going.</h1>
      <p class="mt-2 text-base text-muted-foreground">Pick the week, then choose a section to work on.</p>
    </header>
    <PageGrid aside-title="This conversation">
      <div class="min-w-0 space-y-4">
        <p v-if="loading && !overview" role="status" class="text-sm text-muted-foreground">Opening the chat…</p>
        <Notice v-else-if="problem" role="alert" class="font-medium">{{ problem }}</Notice>

        <template v-else>
          <div :class="!current && 'space-y-6 rounded-3xl border bg-card p-6 shadow-sm sm:p-8'">
          <div class="flex flex-wrap items-end gap-3">
            <div class="space-y-1.5">
              <label for="chat-week" class="block text-xs font-bold text-foreground">Week</label>
              <select id="chat-week" :class="[FIELD, 'h-11 !rounded-full pr-9 pl-4']" :value="period" @change="chooseWeek">
                <option v-for="o in weekOptions" :key="o.period" :value="o.period">{{ o.label }}</option>
              </select>
            </div>
          </div>

          <section aria-labelledby="chat-sections" class="space-y-2">
            <h2 id="chat-sections" :class="current ? 'text-xs font-bold text-foreground' : 'text-xl font-semibold tracking-tight text-cw-accent'">{{ current ? "Sections" : SHOW_CHAT ? "Choose what to talk about" : "Choose a section" }}</h2>
            <ul class="flex flex-wrap gap-2.5">
              <li :class="!current && 'basis-full pb-2'">
                <Button variant="ghost" :class="current ? SECTION_BTN : START_BTN" @click="wholeReport">Whole report</Button>
              </li>
              <li v-for="s in sections" :key="s.slug" class="flex flex-wrap items-center gap-x-3 gap-y-1">
                <Button
                  variant="ghost"
                  :class="SECTION_BTN"
                  :aria-current="s.slug === slug ? 'true' : undefined"
                  :disabled="!s.available"
                  @click="choose(s.slug)"
                >{{ s.title }}</Button>
                <span v-if="!s.available" class="text-sm text-muted-foreground">Not available yet.</span>
              </li>
            </ul>
          </section>
          </div>

          <template v-if="!current && overview">
            <DraftingBanner v-for="d in draftingList(overview).filter(isLive)" :key="d.run_id ?? `${d.report_type}${d.period}${d.slug}`" :drafting="d" />
            <Notice v-if="fullyApproved(overview)" tone="info" role="status">
              <span>{{ APPROVED_BANNER }} <RouterLink to="/previous" :class="LINK">Previous reports</RouterLink></span>
            </Notice>
          </template>

          <section v-if="!current && choices.length" aria-labelledby="chat-recent" class="space-y-3 pt-4">
            <h2 id="chat-recent" class="text-xl font-semibold tracking-tight text-foreground">Recent weeks</h2>
            <ul class="divide-y overflow-hidden rounded-2xl border bg-card">
              <li v-for="c in choices.slice(0, 4)" :key="c.period" class="px-5 py-3.5 text-sm text-foreground">{{ weekChoiceLabel(c) }}</li>
            </ul>
          </section>

          <section v-if="current" aria-labelledby="chat-title" class="mx-auto max-w-[47.5rem] space-y-4 pt-4">
            <PreparePage
              v-if="preparing"
              :section="current"
              :report="report"
              :config="config"
              :drafting="drafting"
              :state="state"
              :conversation-to="viewTo('conversation')"
              :open-on="first(route.query.step)"
              @changed="changed"
              @conversation="router.push(viewTo('conversation'))"
            />
            <template v-else>
            <h2 id="chat-title" class="text-2xl font-normal tracking-tight text-cw-accent">{{ current.title }}</h2>
            <RouterLink v-if="prepares" :to="viewTo('prepare')" :class="['inline-flex min-h-11 items-center text-sm', LINK]">Back to sources and inputs</RouterLink>

            <Notice v-if="notice" tone="flag" role="alert" class="font-medium">{{ notice }}</Notice>
            <Notice v-if="lost" tone="warn" role="alert">{{ lost }}</Notice>

            <ol v-if="SHOW_CHAT" role="log" aria-label="Conversation" class="space-y-4">
              <li v-for="{ m, cards } in rows" :key="m.seq">
                <p v-if="m.role === 'tool'" class="pl-15 text-sm text-muted-foreground">{{ toolLine(m) }}</p>
                <div v-else class="flex items-start gap-4">
                  <span v-if="m.role === 'user'" class="mt-1 flex size-11 shrink-0 items-center justify-center rounded-full border" aria-hidden="true">
                    <PhUser weight="fill" class="size-3.5" />
                  </span>
                  <span v-else class="mt-1" aria-hidden="true"><CytonnMark avatar :size="44" /></span>
                  <div class="min-w-0 flex-1 space-y-2 rounded-3xl px-4 py-3.5" :class="m.role === 'user' ? 'bg-cw-bubble' : 'bg-cw-assistant'">
                    <p class="sr-only">{{ m.role === "user" ? "You" : "Assistant" }}</p>
                    <p v-if="m.content" class="max-w-[70ch] whitespace-pre-wrap text-base leading-7 [overflow-wrap:anywhere]">{{ m.content }}</p>
                    <template v-for="(c, i) in cards" :key="i">
                      <ReadinessCard v-if="c.type === 'readiness' && c.readiness" :readiness="c.readiness" :title="current.title" :at="m.created_at" />
                      <ReviewSummaryCard v-else-if="c.type === 'review_summary' && c.snapshot" :snapshot="c.snapshot" :title="current.title" :at="m.created_at" @full="openFull" />
                      <p v-else class="text-sm text-muted-foreground">Card: {{ c.type.replace(/_/g, " ") }}</p>
                    </template>
                  </div>
                </div>
              </li>
            </ol>

            <div v-if="SHOW_CHAT && status?.kind === 'working'" class="flex items-start gap-4">
              <span class="mt-1" aria-hidden="true"><CytonnMark avatar :size="44" /></span>
              <div role="status" class="flex h-[4.375rem] w-[6.875rem] items-end justify-center gap-2.5 rounded-3xl bg-cw-assistant pb-4">
                <span class="sr-only">{{ status.text }}</span>
                <span v-for="d in 3" :key="d" class="typing-dot size-2.5 rounded-full bg-cw-dots" :style="{ animationDelay: `${(d - 1) * 160}ms` }" aria-hidden="true" />
              </div>
            </div>
            <Notice v-else-if="SHOW_CHAT && status" tone="info" role="status">
              <span class="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span class="inline-flex items-center gap-1.5">
                  <PhPauseCircle weight="bold" class="size-4" aria-hidden="true" />
                  {{ status.text }}
                </span>
                <Button v-if="status.canRaise" variant="outline" @click="convo.raise()">Raise the budget</Button>
              </span>
            </Notice>

            <LiveCards
              v-if="job"
              :job="job"
              :section="current"
              :report="report"
              :drafting="drafting"
              :config="config"
              :old-page="viewTo('prepare')"
              :tick="tick"
              @changed="changed"
              @draft-ended="convo.refresh()"
              @full="openFull"
              @close="choose(null)"
            />

            <form v-if="SHOW_CHAT" class="space-y-2" @submit.prevent="submit">
              <label for="chat-message" class="sr-only">Message</label>
              <div class="rounded-[2.5rem] border border-input p-2 focus-within:ring-[3px] focus-within:ring-ring/50">
                <div class="flex items-end gap-2 rounded-[2rem] bg-card py-1 pr-2 pl-5 shadow-sm">
                  <textarea
                    id="chat-message"
                    v-model="draft"
                    rows="2"
                    maxlength="2000"
                    placeholder="Ask about this section"
                    class="min-h-13 min-w-0 flex-1 resize-none border-0 bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
                    :aria-describedby="off ? 'chat-off' : undefined"
                    @keydown.enter.exact.prevent="submit"
                  />
                  <Button type="submit" class="mb-1.5 rounded-full bg-cw-button text-cw-button-fg hover:bg-cw-button hover:opacity-90 disabled:bg-muted disabled:text-muted-foreground" :disabled="off !== null || !draft.trim()">Send</Button>
                </div>
              </div>
              <p v-if="off" id="chat-off" class="text-sm text-muted-foreground">{{ off }}</p>
            </form>
            <div ref="end" aria-hidden="true" />
            </template>
          </section>
        </template>
      </div>

      <template #aside>
        <FullView v-if="full" :key="`${full.reviewId}-${full.index}`" :review-id="full.reviewId" :index="full.index" @close="full = null" />
        <dl v-if="current" class="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[max-content_1fr] min-[1100px]:grid-cols-1">
          <dt class="eyebrow">Section</dt>
          <dd>{{ current.title }}</dd>
          <dt class="eyebrow">Week</dt>
          <dd>{{ period }}</dd>
          <!-- The chat assistant's own model calls and tokens (jobs.add_usage); a draft's are counted apart, in draft_usage. -->
          <template v-if="SHOW_CHAT && job">
            <dt class="eyebrow">Model calls</dt>
            <dd class="font-mono">{{ job.calls_used }} of {{ job.call_budget }}</dd>
            <dt class="eyebrow">Tokens</dt>
            <dd class="font-mono">{{ used.toLocaleString("en-GB") }} of {{ job.token_budget.toLocaleString("en-GB") }}</dd>
          </template>
        </dl>
        <!-- .rail-stack flattens the aside's direct children, so the tint sits one level in. -->
        <div v-else-if="overview"><div class="space-y-5 rounded-3xl bg-cw-bubble p-6">
          <p class="text-sm text-foreground">{{ SHOW_CHAT ? "Choose a section to start. Each section is its own conversation." : "Choose a section to start." }}</p>

          <!-- The report in figures, counted from the overview's payload (reportCounts in lib/drafting). -->
          <dl role="group" aria-label="This report in figures" class="grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border">
            <div v-for="[label, value, sub, tone] in figures" :key="label" class="bg-card px-3 py-2.5">
              <dt class="text-xs text-muted-foreground">{{ label }}</dt>
              <dd class="font-mono text-lg font-semibold" :class="tone">{{ value }}<span v-if="sub" class="text-xs font-normal text-muted-foreground">{{ sub }}</span></dd>
            </div>
          </dl>
          <dl role="group" aria-label="Sections by state" class="divide-y text-sm">
            <div v-for="[label, value] in tally" :key="label" class="flex items-baseline justify-between gap-3 py-1.5" :class="value === 0 && 'text-muted-foreground'">
              <dt>{{ label }}</dt>
              <dd class="font-mono font-semibold">{{ value }}<span class="text-xs font-normal text-muted-foreground"> / {{ sections.length }}</span></dd>
            </div>
          </dl>
          <ActivityPanel :drafting="draftingList(overview)" :report="report" />

          <section v-if="attention.length" aria-labelledby="chat-attention" class="space-y-1.5">
            <h2 id="chat-attention" class="eyebrow">Needs your attention</h2>
            <ul class="space-y-1">
              <li v-for="a in attention" :key="a.slug">
                <button type="button" :class="ROW" @click="choose(a.slug)">
                  <span class="glyph" :class="a.flag ? 'state-flagged' : 'state-not_auto_verified'" aria-hidden="true">{{ a.flag ? "!" : "?" }}</span>
                  <span class="min-w-0 flex-1">
                    <span class="block font-semibold text-foreground">{{ a.title }}</span>
                    <span class="block text-xs" :class="a.flag ? 'text-flag-fg' : 'text-muted-foreground'">{{ a.why }}</span>
                  </span>
                  <PhCaretRight weight="bold" class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                </button>
              </li>
            </ul>
          </section>

          <section aria-labelledby="chat-aside-sections" class="space-y-1.5">
            <h2 id="chat-aside-sections" class="eyebrow">Sections</h2>
            <ol class="divide-y overflow-hidden rounded-xl border bg-card">
              <SectionRow
                v-for="(s, i) in sections"
                :key="s.slug"
                :s="s"
                :index="i"
                :period="report.period"
                :drafting="draftingFor(draftingList(overview), s.slug, report)"
                :draft-again-off="config ? draftAgainOff(s, draftingFor(draftingList(overview), s.slug, report), config) : null"
                @open="(slug, resume) => openScreen(slug, resume)"
                @redraft="(slug) => openScreen(slug, false)"
              />
            </ol>
          </section>

          <template v-if="report.type === 'weekly'">
            <ExportBar
              :period="report.period"
              :refresh-key="sections.map((s) => `${s.latest?.run_id ?? ''}:${s.latest?.decision ?? ''}`).join('|')"
              @status="(st) => (exportStatus = st)"
              @error="(m) => (exportProblem = m)"
            />
            <ExportNotices :status="exportStatus" :error="exportProblem" />
          </template>
        </div></div>
      </template>
    </PageGrid>
  </main>
</template>
