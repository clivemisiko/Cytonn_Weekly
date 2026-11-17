<script setup lang="ts">
import { PhCircleNotch, PhPauseCircle } from "@phosphor-icons/vue";
import { computed, nextTick, onUnmounted, ref, shallowRef, useTemplateRef, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import PageGrid from "@/components/nav/PageGrid.vue";
import Masthead from "@/components/review/Masthead.vue";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { FIELD, LINK } from "@/components/ui/button";
import * as api from "@/lib/api";
import { cardView, composerOff, createConversation, statusLine, toolLine } from "@/lib/chat";
import { friendlyDate } from "@/lib/format";
import { type BackTarget, useBack } from "@/lib/nav";
import { weekChoiceLabel } from "@/lib/previous";
import { shell, useShellActions, useShellHere, useShellRibbon } from "@/lib/shell";
import type { AppConfig, Overview, WeekChoice } from "@/lib/types";

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

const convo = createConversation(api.chatApi);
const { job, messages, notice, lost, sending } = convo;
onUnmounted(convo.stop);

const period = computed(() => (WEEK.test(first(route.query.period)) ? first(route.query.period) : defaultPeriod.value));
const slug = computed(() => first(route.query.section) || null);
const sections = computed(() => overview.value?.sections ?? []);
const current = computed(() => sections.value.find((s) => s.slug === slug.value) ?? null);
const weekOptions = computed(() => {
  const list = choices.value.map((c) => ({ period: c.period, label: weekChoiceLabel(c) }));
  const p = period.value;
  return p && !list.some((o) => o.period === p) ? [{ period: p, label: friendlyDate(p.slice("Week ending ".length)) }, ...list] : list;
});

const oldPage = (section: string) => ({ path: "/overview", query: { report: "weekly", period: period.value, section } });
const status = computed(() => statusLine(job.value));
const off = computed(() => composerOff(job.value, config.value, sending.value));
const used = computed(() => (job.value ? job.value.input_tokens + job.value.output_tokens : 0));

function choose(next: string | null) {
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
  try {
    if (!config.value) {
      const [c, weeks] = await Promise.all([api.getConfig(), api.getPreviousWeeks()]);
      config.value = c;
      shell.config.value = c;
      choices.value = weeks.choices ?? [];
      defaultPeriod.value = api.weekPeriod(weeks.default_week_ending);
    }
    overview.value = await api.getOverview({ type: "weekly", period: period.value, kind: null });
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
useShellActions({ openSection: choose, toOverview: () => void router.push({ path: "/overview", query: { report: "weekly", period: period.value } }) });
useBack((): BackTarget => (slug.value ? { kind: "go", to: "the section list", go: () => choose(null) } : { kind: "home" }));
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
                <RouterLink :to="oldPage(s.slug)" :class="['text-sm', LINK]" :aria-label="`Old page for ${s.title}`">Old page</RouterLink>
              </li>
            </ul>
          </section>

          <section v-if="current" aria-labelledby="chat-title" class="space-y-3">
            <h2 id="chat-title" class="text-lg font-semibold tracking-tight">{{ current.title }}</h2>

            <Notice v-if="notice" tone="flag" role="alert" class="font-medium">{{ notice }}</Notice>
            <Notice v-if="lost" tone="warn" role="alert">{{ lost }}</Notice>

            <ol role="log" aria-label="Conversation" class="space-y-3">
              <li v-for="m in messages" :key="m.seq">
                <p v-if="m.role === 'tool'" class="text-sm text-muted-foreground">{{ toolLine(m) }}</p>
                <div v-else class="space-y-2 rounded-lg border px-3.5 py-2.5" :class="m.role === 'user' ? 'bg-muted' : 'bg-card'">
                  <p class="eyebrow">{{ m.role === "user" ? "You" : "Assistant" }}</p>
                  <p v-if="m.content" class="max-w-[70ch] whitespace-pre-wrap text-base leading-7 [overflow-wrap:anywhere]">{{ m.content }}</p>
                  <section v-for="(card, i) in m.cards ?? []" :key="i" :aria-label="cardView(card).title" class="space-y-2 rounded-md border bg-background px-3 py-2.5">
                    <h3 class="text-sm font-semibold">{{ cardView(card).title }}</h3>
                    <div v-for="b in cardView(card).blocks" :key="b.heading" class="space-y-1">
                      <p class="eyebrow">{{ b.heading }}</p>
                      <ul class="list-disc space-y-0.5 pl-5 text-sm [overflow-wrap:anywhere]">
                        <li v-for="line in b.lines" :key="line">{{ line }}</li>
                      </ul>
                    </div>
                  </section>
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
          <dt class="eyebrow">Page</dt>
          <dd><RouterLink :to="oldPage(current.slug)" :class="LINK">Old page for this section</RouterLink></dd>
        </dl>
        <p v-else class="text-sm text-muted-foreground">Choose a section to start. Each section is its own conversation.</p>
      </template>
    </PageGrid>
  </main>
</template>
