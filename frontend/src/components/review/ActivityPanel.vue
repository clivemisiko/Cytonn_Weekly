<script setup lang="ts">
import { PhArrowRight } from "@phosphor-icons/vue";
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { LINK } from "@/components/ui/button";
import { draftingStatus } from "@/lib/drafting";
import { elapsed, friendlyTime } from "@/lib/format";
import { textOf } from "@/lib/run";
import type { Drafting, ReportChoice } from "@/lib/types";

// Only what the server reports for this report: each draft running, queued, or whose newest run failed, with the last
// step it reported. Times come from the payload, which the overview re-reads every few seconds while a draft is live.
const props = defineProps<{ drafting: Drafting[]; report: ReportChoice }>();
const mine = computed(() => props.drafting.filter((d) => (d.report_type ?? "weekly") === props.report.type && (d.period ?? "") === props.report.period));
const TAG = { running: "Drafting", queued: "Queued", failed: "Stopped" } as const;
</script>

<template>
  <!-- Nothing at all while no run is live or stopped: an empty activity panel would only be filler. -->
  <section v-if="mine.length" aria-labelledby="activity-title" class="space-y-3">
    <h3 id="activity-title" class="panel-title">Drafting activity</h3>
    <ol class="space-y-4">
      <li v-for="d in mine" :key="d.run_id ?? d.slug" class="space-y-1 border-l-2 pl-3" :class="d.state === 'failed' ? 'border-flag' : 'border-input'">
        <p class="flex flex-wrap items-baseline gap-x-2 font-mono text-xs text-muted-foreground">
          <span>{{ friendlyTime(d.started_at) }}</span>
          <span class="font-semibold" :class="d.state === 'failed' ? 'text-flag-fg' : 'text-foreground'">[{{ TAG[d.state ?? "running"] }}]</span>
        </p>
        <p class="text-sm font-semibold">{{ d.title }}</p>
        <p class="text-sm text-muted-foreground">
          <template v-if="d.state === 'failed'">{{ d.reason ?? "The draft stopped." }}</template>
          <template v-else-if="d.state === 'queued'">{{ draftingStatus(d) }}</template>
          <template v-else>{{ d.step ? textOf(d.step) : "Started; no step reported yet." }} · <span class="font-mono">{{ elapsed(d.elapsed_seconds) }}</span></template>
        </p>
        <RouterLink v-if="d.run_id" :to="`/runs/${d.run_id}`" :class="['inline-flex items-center gap-1 text-sm font-medium', LINK]">
          Open the run<PhArrowRight weight="bold" class="size-3.5" aria-hidden="true" />
        </RouterLink>
      </li>
    </ol>
  </section>
</template>
