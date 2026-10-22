<script setup lang="ts">
import { PhArrowSquareOut, PhCaretDown, PhCaretUp, PhChartLineUp } from "@phosphor-icons/vue";
import { computed, ref, useId } from "vue";
import Button from "@/components/ui/Button.vue";
import { ApiError, chartImageUrl, getChartSeries } from "@/lib/api";
import { chartFacts, chartState, pictureProblem, plottedPoints, provenanceLine, teamChartAction } from "@/lib/chart";
import { friendlyDate } from "@/lib/format";
import type { ChartBlock, ChartSeriesFile, Review } from "@/lib/types";
import Notice from "./Notice.vue";
import Numeral from "./Numeral.vue";

/**
 * One chart the tool draws from the analyst workbook: the picture, the facts it rests on, the rows left out of the series and the
 * plotted points on request. Every notice about the chart is here, in the draft's column, or in the review items beside it; none
 * is in a panel that folds. The one choice it offers is "Use the team's own chart", which the parent saves with the review.
 */
const props = defineProps<{ review: Review; block: ChartBlock; onTeamChart: (chartId: string, use: boolean) => Promise<boolean> }>();

const uid = useId();
const state = computed(() => chartState(props.block));
const facts = computed(() => chartFacts(props.block));
const action = computed(() => teamChartAction(props.block));
const imageUrl = computed(() => chartImageUrl(props.review.run_id, props.block.chart_id));
const stops = computed(() => props.block.defects.filter((d) => d.blocking));
const leftOut = computed(() => props.block.defects.filter((d) => !d.blocking));
const drawn = computed(() => props.block.status === "drawn");

// The picture: if the API refuses it (a changed or missing file) the card says why instead of showing a broken image.
const pictureError = ref<string | null>(null);
async function pictureFailed() {
  let status: number | null = null;
  try {
    status = (await fetch(imageUrl.value, { cache: "no-store" })).status;
  } catch {
    /* the API is unreachable: the message says so */
  }
  pictureError.value = pictureProblem(status, "The picture is");
}

// The plotted points are read only when asked for, from the same hash-checked store as the picture.
const showPoints = ref(false);
const series = ref<ChartSeriesFile | null>(null);
const pointsError = ref<string | null>(null);
const loadingPoints = ref(false);
const points = computed(() => (series.value ? plottedPoints(series.value, props.block.window?.first ?? null) : []));
async function togglePoints() {
  showPoints.value = !showPoints.value;
  if (!showPoints.value || series.value || loadingPoints.value) return;
  loadingPoints.value = true;
  pointsError.value = null;
  try {
    series.value = await getChartSeries(props.review.run_id, props.block.chart_id);
  } catch (err) {
    pointsError.value = pictureProblem(err instanceof ApiError ? err.status : null, "The plotted points are");
  } finally {
    loadingPoints.value = false;
  }
}

const busy = ref(false);
async function chooseTeamChart() {
  busy.value = true;
  try {
    await props.onTeamChart(props.block.chart_id, !props.block.use_team_chart);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section
    class="space-y-3 border-t px-4 py-6 sm:px-6"
    :aria-labelledby="`blk-${block.id}`"
    data-chart-block
    :data-chart-state="state.key"
  >
    <h3 :id="`blk-${block.id}`" class="flex flex-wrap items-center gap-3 text-base font-semibold">
      <Numeral>{{ block.numeral }}</Numeral>
      {{ block.title }}
      <span class="inline-flex items-center gap-1 rounded-full border border-input px-2 py-0.5 text-xs font-semibold text-muted-foreground">
        <PhChartLineUp weight="bold" class="size-3" aria-hidden="true" />
        {{ state.label }}
      </span>
    </h3>
    <p class="max-w-[68ch] text-sm md:pl-11">{{ block.caption }}</p>

    <!-- Notices: in the draft's column, never in a panel that folds. -->
    <div class="space-y-2 empty:hidden md:pl-11">
      <Notice v-if="block.status === 'no_workbook'" tone="info" role="status">
        <span class="block">{{ block.reason }}</span>
        <span class="mt-1 block"><span class="font-semibold">Unblocked by:</span> {{ block.unblock }}</span>
        <span class="mt-1 block">
          Until then the tool draws no chart: the Word file keeps the placeholder for the team's own Excel chart. Nothing here needs
          resolving.
        </span>
      </Notice>
      <Notice v-if="block.use_team_chart" tone="info" role="status" class="font-medium">
        Using the team's own chart. The tool's chart is set aside and this chart's review items are accepted as not used. The Word file
        keeps the placeholder "[Chart to add: {{ block.caption }}]" for the team's Excel chart.
      </Notice>
      <Notice v-for="d in stops" :key="d.kind + d.message" tone="flag">
        <strong class="font-semibold">Not drawn.</strong> {{ d.message }}
      </Notice>
    </div>

    <figure v-if="drawn" class="space-y-2 md:pl-11">
      <div class="rounded-md border bg-chart-frame p-2">
        <img
          v-if="!pictureError"
          :src="imageUrl"
          :alt="block.alt ?? block.caption"
          width="1200"
          height="600"
          class="block h-auto w-full"
          @error="pictureFailed"
        />
        <p v-else role="alert" class="p-4 text-sm font-medium text-flag-fg">{{ pictureError }}</p>
      </div>
      <figcaption class="text-xs">
        <a
          :href="imageUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex min-h-6 items-center gap-1 text-link underline decoration-link/40 underline-offset-2 hover:decoration-link"
        >
          Open full size<PhArrowSquareOut weight="bold" class="size-4" aria-hidden="true" /><span class="sr-only"> (opens in a new tab)</span>
        </a>
      </figcaption>
    </figure>

    <dl v-if="facts.length > 0" class="grid gap-2 @min-[34rem]:grid-cols-2 md:pl-11" aria-label="What the chart rests on">
      <div v-for="f in facts" :key="f.label" class="min-w-0 rounded-sm border bg-card px-3 py-2">
        <dt class="text-xs text-muted-foreground">{{ f.label }}</dt>
        <dd class="mt-1 text-sm font-medium [overflow-wrap:anywhere]">{{ f.value }}</dd>
      </div>
    </dl>
    <p v-if="provenanceLine(block)" class="text-xs text-muted-foreground md:pl-11">{{ provenanceLine(block) }}</p>
    <p v-if="block.average?.note" class="text-xs text-muted-foreground md:pl-11">{{ block.average.note }}</p>

    <!-- Rows the reader left out of the series (listed by cell, never repaired). The same defects are review items beside the draft. -->
    <div v-if="drawn && leftOut.length > 0" class="space-y-2 md:pl-11">
      <Notice v-for="d in leftOut" :key="d.kind + d.message" tone="warn">{{ d.message }}</Notice>
    </div>

    <div v-if="block.status !== 'no_workbook'" class="space-y-2 md:pl-11">
      <div class="flex flex-wrap items-center gap-2">
        <Button
          v-if="drawn"
          variant="ghost"
          size="sm"
          :aria-expanded="showPoints"
          :aria-controls="`${uid}-points`"
          @click="togglePoints"
        >
          <component :is="showPoints ? PhCaretUp : PhCaretDown" weight="bold" aria-hidden="true" />{{ showPoints ? "Hide points" : "Show points" }}
        </Button>
        <Button
          variant="outline"
          size="sm"
          :disabled="review.locked || busy"
          :aria-describedby="`${uid}-own`"
          @click="chooseTeamChart"
        >
          {{ action.label }}
        </Button>
      </div>
      <p :id="`${uid}-own`" class="max-w-[68ch] text-xs text-muted-foreground">
        {{ review.locked ? "This review is decided, so the choice is frozen." : action.help }}
      </p>
    </div>

    <div v-if="drawn && showPoints" :id="`${uid}-points`" class="space-y-2 md:pl-11">
      <p v-if="loadingPoints" role="status" class="text-sm text-muted-foreground">Reading the stored points…</p>
      <Notice v-else-if="pointsError" tone="flag" role="alert">{{ pointsError }}</Notice>
      <div
        v-else
        role="region"
        :aria-label="`Plotted points of ${block.title}, newest first`"
        tabindex="0"
        class="max-h-72 overflow-auto rounded-md border focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <table class="w-full border-collapse text-xs">
          <caption class="sr-only">
            {{ points.length }} points shown, from {{ block.window ? friendlyDate(block.window.first) : "the first point" }}, newest first.
          </caption>
          <thead>
            <tr class="sticky top-0 border-b bg-muted">
              <th scope="col" class="eyebrow px-3 py-2 text-left">Date</th>
              <th scope="col" class="eyebrow px-3 py-2 text-right">Value</th>
              <th scope="col" class="eyebrow px-3 py-2 text-left">Cell</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in points" :key="p.date" class="border-b last:border-b-0">
              <td class="px-3 py-1 whitespace-nowrap">{{ friendlyDate(p.date) }}</td>
              <td class="px-3 py-1 text-right">{{ p.value }}</td>
              <td class="px-3 py-1 font-mono text-muted-foreground">{{ p.cell }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
