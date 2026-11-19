<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from "vue";
import ExportBar from "@/components/review/ExportBar.vue";
import Notice from "@/components/review/Notice.vue";
import * as api from "@/lib/api";
import type { Job } from "@/lib/chat";
import { draftCard, hasNeeds, needsYou, parseReadiness, type Readiness } from "@/lib/chatcards";
import type { AppConfig, Drafting, ReportChoice, Review, SectionSummary } from "@/lib/types";
import DraftCard from "./DraftCard.vue";
import FundSnipCard from "./FundSnipCard.vue";
import LiveReviewCard from "./LiveReviewCard.vue";
import NeedsYouCard from "./NeedsYouCard.vue";
import SourcesCard from "./SourcesCard.vue";
import TypedInputsCard from "./TypedInputsCard.vue";

const props = defineProps<{
  job: Job;
  section: SectionSummary;
  report: ReportChoice;
  drafting: Drafting | null;
  config: AppConfig | null;
  /** The old page's address for this section: where the inputs form, the sources and the snips are. */
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
    <h2 id="live-title" class="eyebrow">What you can do now</h2>

    <Notice v-if="readinessProblem" tone="warn" role="alert">{{ readinessProblem }}</Notice>
    <p v-else-if="needs && !hasNeeds(needs)" class="text-sm text-muted-foreground">Nothing is missing for this section.</p>

    <NeedsYouCard v-if="needs && formNeeds" :needs="needs" :week="week" :section="section.slug" :form-to="oldPage" @changed="done" />
    <TypedInputsCard v-if="weekly && needs?.inline.length" :entries="needs.inline" :week="week" :section="section.slug" @changed="done" />
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
