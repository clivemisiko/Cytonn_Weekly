<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import * as api from "@/lib/api";
import { NEEDS_TITLES } from "@/lib/sources";
import { sectionTitles } from "@/lib/topic";
import type { GatherLook, ReportChoice, SectionSummary, SourceMeta, SourcePiece, SourcesListing } from "@/lib/types";
import Notice from "./Notice.vue";
import SourcePieceCard from "./SourcePieceCard.vue";

/**
 * The pages each piece of this section is written from (Amazon Bedrock drafts only; the screen shows it for no other
 * provider). The tool searches for them when a draft starts and the analyst can add more; a piece with no source comes
 * back unavailable, and every quote it uses is checked against the saved text. The panel holds what an analyst must
 * act on, so it never folds.
 */
const props = defineProps<{
  section: SectionSummary;
  report: ReportChoice;
  /** A Focus's typed section titles, one per line: they name its pieces. */
  titles: string;
  disabled: boolean;
}>();
const emit = defineEmits<{ pieces: [pieces: SourcePiece[] | null] }>();

const LOOK_UP_AFTER_MS = 400; // a Focus's titles are looked up once typing pauses
const listing = ref<SourcesListing | null>(null);
const error = ref<string | null>(null);
const loading = ref(false);
const needsTitles = computed(() => props.section.needs_topic && sectionTitles(props.titles).length === 0);

let latest = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
async function load() {
  const mine = ++latest;
  if (needsTitles.value) {
    listing.value = null;
    error.value = null;
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    const next = await api.getSources(props.section.slug, props.report, props.titles);
    if (mine !== latest) return; // a newer lookup is under way
    listing.value = next;
    error.value = null;
  } catch (err) {
    if (mine !== latest) return;
    listing.value = null;
    error.value = (err as api.ApiError).message;
  } finally {
    if (mine === latest) loading.value = false;
  }
}
// Another section or report must never show the last one's pieces while its own are read.
watch(
  () => [props.section.slug, props.report.type, props.report.period] as const,
  () => {
    latest++;
    listing.value = null;
    error.value = null;
  },
);
watch(
  () => [props.section.slug, props.report.type, props.report.period, props.titles] as const,
  () => {
    clearTimeout(timer);
    timer = setTimeout(load, props.section.needs_topic ? LOOK_UP_AFTER_MS : 0);
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  clearTimeout(timer);
  latest++;
});

const pieces = computed(() => listing.value?.pieces ?? []);
// What the screen knows of which pieces lack sources: null while it does not know, so it never names one by guess.
watch([listing, needsTitles], () => emit("pieces", listing.value ? listing.value.pieces : needsTitles.value ? [] : null), { deep: true, immediate: true });
function update(subject: string, sources: SourceMeta[], gather?: GatherLook | null) {
  if (!listing.value) return;
  const piece = listing.value.pieces.find((p) => p.subject === subject);
  if (!piece) return;
  piece.sources = sources;
  if (gather !== undefined) piece.gather = gather;
}
const sites = computed(() => listing.value?.approved_sites ?? []);
</script>

<template>
  <section v-if="!listing || listing.uses_sources" aria-labelledby="sources-title" class="space-y-4 rounded-lg border border-t-[3px] border-t-primary bg-card p-6">
    <div class="space-y-1">
      <h2 id="sources-title" class="text-lg font-semibold">Sources</h2>
      <p class="text-sm text-muted-foreground">
        Amazon Bedrock writes only from the pages saved here; it has no search of its own. The tool looks for sources itself when a draft starts, and you can
        search for them now or add more: paste a page’s text with its address and date, or fetch a page from its address. Remove any page you do not want.
        Every quote a claim uses is checked against the saved text, and you see it on the review.
      </p>
    </div>

    <p v-if="needsTitles" role="status" class="text-sm">{{ NEEDS_TITLES }}</p>
    <p v-else-if="loading && !listing" role="status" class="text-sm text-muted-foreground">Reading the saved sources…</p>
    <Notice v-if="error" role="alert" class="font-medium">{{ error }}</Notice>

    <ul v-if="pieces.length" class="space-y-3" aria-label="Pieces of this section">
      <SourcePieceCard
        v-for="(p, i) in pieces"
        :key="`${section.slug}:${p.subject}`"
        :piece="p"
        :uid="`${section.slug}-${i}`"
        :slug="section.slug"
        :report="report"
        :titles="titles"
        :disabled="disabled"
        @update="(s, g) => update(p.subject, s, g)"
      />
    </ul>

    <details v-if="sites.length" class="text-sm">
      <summary class="cursor-pointer rounded-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">Known sites ({{ sites.length }})</summary>
      <ul class="mt-2 grid gap-x-6 gap-y-1 font-mono text-xs sm:grid-cols-2">
        <li v-for="s in sites" :key="s" class="[overflow-wrap:anywhere]">{{ s }}</li>
      </ul>
    </details>
  </section>
</template>
