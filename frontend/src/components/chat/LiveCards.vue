<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from "vue";
import ExportBar from "@/components/review/ExportBar.vue";
import Notice from "@/components/review/Notice.vue";
import * as api from "@/lib/api";
import type { Job } from "@/lib/chat";
import { draftCard, hasNeeds, needsYou, parseReadiness, type Readiness } from "@/lib/chatcards";
import { type Step, itemSteps, openingStep } from "@/lib/prepare";
import type { AnalystForm, AppConfig, Drafting, ReportChoice, Review, SectionSummary } from "@/lib/types";
import DraftCard from "./DraftCard.vue";
import FundSnipCard from "./FundSnipCard.vue";
import LiveReviewCard from "./LiveReviewCard.vue";
import NeedsYouCard from "./NeedsYouCard.vue";
import SourcesCard from "./SourcesCard.vue";
import InputSteps from "./InputSteps.vue";

const props = defineProps<{
  job: Job;
  section: SectionSummary;
  report: ReportChoice;
  drafting: Drafting | null;
  config: AppConfig | null;
  /** The prepare page's address for this section: where its inputs, sources and snips are. A card adds `&step=` to it. */
  oldPage: string;
  /** Counted up by the page after anything changed, so the cards read again. */
  tick: number;
}>();
const emit = defineEmits<{
  /** A button changed something: the page reads the report again so the rail and the overview never show the old state. */
  changed: [];
  /** A draft ended: the conversation reads its new messages (the review summary card the code saved). */
  draftEnded: [];
  full: [reviewId: number, index: number | null];
  close: [];
}>();

const readiness = shallowRef<Readiness | null>(null);
const readinessProblem = ref<string | null>(null);
const review = shallowRef<Review | null>(null);
const exportProblem = ref<string | null>(null);
let generation = 0;

/** Everything on these cards is read from the server now: nothing is carried from an earlier read. */
async function read() {
  const mine = ++generation;
  try {
    const got = parseReadiness(((await api.getReadiness(props.job.job_id)) as { readiness: unknown }).readiness);
    if (mine === generation) {
      readiness.value = got;
      readinessProblem.value = got ? null : "The readiness check came back in a shape this page does not know.";
    }
  } catch (err) {
    if (mine === generation) readinessProblem.value = (err as Error).message;
  }
  const latest = props.section.latest;
  if (!latest || !(latest.current ?? latest.this_week)) {
    if (mine === generation) review.value = null;
    return;
  }
  try {
    const next = await api.getReview(latest.run_id);
    if (mine === generation) review.value = next;
  } catch {
    if (mine === generation) review.value = null;
  }
}

watch(() => [props.tick, props.job.job_id, props.section.latest?.run_id, props.section.latest?.decision], read, { immediate: true });
onUnmounted(() => generation++);

const needs = computed(() => (readiness.value ? needsYou(readiness.value) : null));
// The typed inputs: the prepare page's own stepper over every form item (the fund table keeps its own card here). Its steps
// are captured once, when the form is first read, so later reads never add, drop or reorder them.
const form = shallowRef<AnalystForm | null>(null);
const typedSteps = shallowRef<Step[] | null>(null);
const liveTitle = ref<HTMLElement | null>(null);
watch(() => `${props.job.job_id} ${props.section.slug} ${props.report.period}`, () => {
  form.value = null;
  typedSteps.value = null;
});
watch(readiness, async (r) => {
  if (!r || form.value || !weekly.value || !Object.values(r.groups).some((g) => g.some((e) => e.kind !== "upload"))) return;
  try {
    form.value = await api.getAnalystInputs(week.value, props.section.slug);
    typedSteps.value ??= itemSteps(form.value, false);
  } catch {
    /* the needs-you card still lists what is missing */
  }
});
const missing = computed(() => (readiness.value ? [...readiness.value.groups.needs_analyst, ...readiness.value.groups.carried_or_suggested].map((e) => e.key) : []));
const formNeeds = computed(() => !!needs.value && hasNeeds({ ...needs.value, inline: [] }));
const draft = computed(() => draftCard(props.section, props.drafting, props.config));
const counted = computed(() => readiness.value !== null && (readiness.value.snips !== null || readiness.value.sources !== null));
const weekly = computed(() => props.report.type === "weekly" && !!props.report.period);
const week = computed(() => props.report.period.replace(/^Week ending /, ""));
const ended = () => {
  emit("draftEnded");
  done();
};
const done = () => {
  emit("changed");
  void read();
};
</script>

<template>
  <section aria-labelledby="live-title" class="space-y-3" data-card="live">
    <h2 id="live-title" ref="liveTitle" tabindex="-1" class="eyebrow outline-none">What you can do now</h2>

    <Notice v-if="readinessProblem" tone="warn" role="alert">{{ readinessProblem }}</Notice>
    <p v-else-if="needs && !hasNeeds(needs)" class="text-sm text-muted-foreground">Nothing is missing for this section.</p>

    <NeedsYouCard v-if="needs && formNeeds" :needs="needs" :week="week" :section="section.slug" :form-to="oldPage" @changed="done" />
    <InputSteps
      v-if="weekly && typedSteps?.length"
      :key="job.job_id"
      :steps="typedSteps"
      :form="form"
      :week="week"
      :section="section.slug"
      :missing="missing"
      :start="openingStep(typedSteps, missing)"
      heading="Type these here"
      data-card="typed_inputs"
      @form="(f) => (form = f)"
      @done="liveTitle?.focus()"
      @changed="done"
    />
    <FundSnipCard v-if="weekly && section.slug === 'fixed_income'" :week="week" :section="section.slug" @changed="done" />
    <SourcesCard v-if="readiness && counted" :readiness="readiness" :old-page="oldPage" />
    <DraftCard v-if="draft.kind !== 'none'" :section="section" :card="draft" :report="report" :config="config" :old-page="oldPage" @changed="done" @ended="ended" />
    <LiveReviewCard v-if="review" :key="review.run_id" :initial="review" @full="(id, i) => emit('full', id, i)" @decided="done" @close="emit('close')" />
    <template v-if="weekly">
      <ExportBar rows :period="report.period" :refresh-key="`${tick}-${section.latest?.run_id ?? 0}-${section.latest?.decision ?? ''}`" @error="(m) => (exportProblem = m)" />
      <Notice v-if="exportProblem" role="alert" class="font-medium">{{ exportProblem }}</Notice>
    </template>
  </section>
</template>
