<script setup lang="ts">
import { PhCircleNotch, PhPauseCircle } from "@phosphor-icons/vue";
import { computed, nextTick, onUnmounted, ref, shallowRef, useTemplateRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import FullView from "@/components/chat/FullView.vue";
import LiveCards from "@/components/chat/LiveCards.vue";
import ReadinessCard from "@/components/chat/ReadinessCard.vue";
import ReviewSummaryCard from "@/components/chat/ReviewSummaryCard.vue";
import PageGrid from "@/components/nav/PageGrid.vue";
import Masthead from "@/components/review/Masthead.vue";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { FIELD } from "@/components/ui/button";
import * as api from "@/lib/api";
import { type ChatCard, composerOff, createConversation, statusLine, toolLine } from "@/lib/chat";
import { parseReadiness, parseReviewSnapshot } from "@/lib/chatcards";
import { draftingFor, draftingList } from "@/lib/drafting";
import { friendlyDate } from "@/lib/format";
import { BACK_NONE, type BackTarget, useBack } from "@/lib/nav";
import { weekChoiceLabel } from "@/lib/previous";
import { shell, useShellActions, useShellHere, useShellRibbon } from "@/lib/shell";
import type { AppConfig, Overview, ReportChoice, WeekChoice } from "@/lib/types";

const route = useRoute();
const router = useRouter();
const first = (v: unknown) => (Array.isArray(v) ? String(v[0] ?? "") : typeof v === "string" ? v : "");
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
const drafting = computed(() => (overview.value && current.value ? draftingFor(draftingList(overview.value), current.value.slug, report.value) : null));

// The hidden page a chat button opens (the inputs form, the snips and sources, the Focus topic); there it shows "Back to chat".
const oldPage = (section: string) => `/overview?${new URLSearchParams({ report: "weekly", period: period.value, section, from: "chat" }).toString()}`;
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
      defaultPeriod.value = api.weekPeriod(weeks.default_week_ending);
    }
    overview.value = await api.getOverview(report.value);
    shell.setOverview(overview.value); // the rail takes the same payload
    const wanted = slug.value;
    if (wanted && overview.value.sections.some((s) => s.slug === wanted && s.available)) await convo.open(wanted, period.value);
    else convo.stop();
  } catch (err) {
    problem.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}
watch(() => [route.query.section, route.query.period], load, { immediate: true });

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
  <main id="main" tabindex="-1">
    <Masthead wide title="Chat" />
    <PageGrid aside-title="This conversation">
      <div class="min-w-0 space-y-4">
        <p v-if="loading && !overview" role="status" class="text-sm text-muted-foreground">Opening the chat…</p>
        <Notice v-else-if="problem" role="alert" class="font-medium">{{ problem }}</Notice>

        <template v-else>
          <div class="flex flex-wrap items-end gap-3">
            <div class="space-y-1">
              <label for="chat-week" class="eyebrow block">Week</label>
              <select id="chat-week" :class="[FIELD, 'pr-8']" :value="period" @change="chooseWeek">
                <option v-for="o in weekOptions" :key="o.period" :value="o.period">{{ o.label }}</option>
              </select>
            </div>
          </div>

          <section aria-labelledby="chat-sections" class="space-y-2">
            <h2 id="chat-sections" class="eyebrow">{{ current ? "Sections" : "Choose what to talk about" }}</h2>
            <ul class="space-y-2">
              <li>
                <Button variant="outline" @click="wholeReport">Whole report</Button>
              </li>
              <li v-for="s in sections" :key="s.slug" class="flex flex-wrap items-center gap-x-4 gap-y-1">
                <Button variant="outline" :aria-current="s.slug === slug ? 'true' : undefined" :disabled="!s.available" @click="choose(s.slug)">{{ s.title }}</Button>
                <span v-if="!s.available" class="text-sm text-muted-foreground">Not available yet.</span>
              </li>
            </ul>
          </section>

          <section v-if="current" aria-labelledby="chat-title" class="space-y-3">
            <h2 id="chat-title" class="text-lg font-semibold tracking-tight">{{ current.title }}</h2>

            <Notice v-if="notice" tone="flag" role="alert" class="font-medium">{{ notice }}</Notice>
            <Notice v-if="lost" tone="warn" role="alert">{{ lost }}</Notice>

            <ol role="log" aria-label="Conversation" class="space-y-3">
              <li v-for="{ m, cards } in rows" :key="m.seq">
                <p v-if="m.role === 'tool'" class="text-sm text-muted-foreground">{{ toolLine(m) }}</p>
                <div v-else class="space-y-2 rounded-lg border px-3.5 py-2.5" :class="m.role === 'user' ? 'bg-muted' : 'bg-card'">
                  <p class="eyebrow">{{ m.role === "user" ? "You" : "Assistant" }}</p>
                  <p v-if="m.content" class="max-w-[70ch] whitespace-pre-wrap text-base leading-7 [overflow-wrap:anywhere]">{{ m.content }}</p>
                  <template v-for="(c, i) in cards" :key="i">
                    <ReadinessCard v-if="c.type === 'readiness' && c.readiness" :readiness="c.readiness" :title="current.title" :at="m.created_at" />
                    <ReviewSummaryCard v-else-if="c.type === 'review_summary' && c.snapshot" :snapshot="c.snapshot" :title="current.title" :at="m.created_at" @full="openFull" />
                    <p v-else class="text-sm text-muted-foreground">Card: {{ c.type.replace(/_/g, " ") }}</p>
                  </template>
                </div>
              </li>
            </ol>

            <Notice v-if="status" tone="info" role="status">
              <span class="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span class="inline-flex items-center gap-1.5">
                  <PhCircleNotch v-if="status.kind === 'working'" weight="bold" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  <PhPauseCircle v-else weight="bold" class="size-4" aria-hidden="true" />
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
              :old-page="oldPage(current.slug)"
              :tick="tick"
              @changed="changed"
              @draft-ended="convo.refresh()"
              @full="openFull"
              @close="choose(null)"
            />

            <form class="space-y-2" @submit.prevent="submit">
              <label for="chat-message" class="eyebrow block">Message</label>
              <textarea
                id="chat-message"
                v-model="draft"
                rows="3"
                maxlength="2000"
                :class="[FIELD, 'h-auto w-full py-2']"
                :aria-describedby="off ? 'chat-off' : undefined"
                @keydown.enter.exact.prevent="submit"
              />
              <p v-if="off" id="chat-off" class="text-sm text-muted-foreground">{{ off }}</p>
              <Button type="submit" :disabled="off !== null || !draft.trim()">Send</Button>
            </form>
            <div ref="end" aria-hidden="true" />
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
          <template v-if="job">
            <dt class="eyebrow">Model calls</dt>
            <dd class="font-mono">{{ job.calls_used }} of {{ job.call_budget }}</dd>
            <dt class="eyebrow">Tokens</dt>
            <dd class="font-mono">{{ used.toLocaleString("en-GB") }} of {{ job.token_budget.toLocaleString("en-GB") }}</dd>
          </template>
        </dl>
        <p v-else class="text-sm text-muted-foreground">Choose a section to start. Each section is its own conversation.</p>
      </template>
    </PageGrid>
  </main>
</template>
