<script setup lang="ts">
import { PhDownloadSimple } from "@phosphor-icons/vue";
import { ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import type { Review } from "@/lib/types";
import Notice from "./Notice.vue";

const props = defineProps<{ review: Review }>();
const busy = ref(false);
const error = ref<string | null>(null);
// The export status says whether this section's newest run is still drafting, failed or only placeholders.
const blocked = ref<string | null>(null);

watch(
  () => [props.review.period, props.review.section_slug, props.review.run_id],
  (_now, _before, onCleanup) => {
    let live = true;
    onCleanup(() => (live = false));
    api
      .getExportStatus(props.review.period)
      .then((s) => {
        const why = s.sections.find((x) => x.slug === props.review.section_slug)?.left_out_reason;
        if (live) blocked.value = why ? `Not available: ${why}.` : null;
      })
      .catch(() => live && (blocked.value = null)); // the download itself reports any refusal
  },
  { immediate: true },
);

async function download() {
  busy.value = true;
  error.value = null;
  try {
    api.saveFile(await api.exportSection(props.review.period, props.review.section_slug));
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div v-if="review.report_type === 'weekly'" class="space-y-1">
    <Button variant="outline" size="sm" :disabled="busy || !!blocked" :aria-describedby="blocked ? `dl-why-${review.run_id}` : undefined" @click="download">
      <PhDownloadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
      {{ busy ? "Preparing…" : "Download this section" }}
    </Button>
    <p v-if="blocked" :id="`dl-why-${review.run_id}`" class="text-xs text-muted-foreground">{{ blocked }}</p>
    <Notice v-if="error" data-problem role="alert" class="font-medium">{{ error }}</Notice>
  </div>
</template>
