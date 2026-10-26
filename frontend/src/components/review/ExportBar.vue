<script setup lang="ts">
import { PhCheck, PhDownloadSimple, PhQuestion, PhWarning } from "@phosphor-icons/vue";
import { computed, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import type { ExportStatus } from "@/lib/types";

const STATE_LABEL: Record<string, string> = {
  approved: "Approved",
  in_review: "In review",
  rejected: "Rejected",
  not_drafted: "Not drafted",
};

const props = defineProps<{ period: string; refreshKey: string }>();
const emit = defineEmits<{ status: [status: ExportStatus | null]; error: [message: string | null] }>();
const status = ref<ExportStatus | null>(null);
watch(status, (now) => emit("status", now), { immediate: true });
const busy = ref(false);
const error = ref<string | null>(null);
// The error is shown by the screen, in its feed: this bar sits in a panel that can be folded (the panel rule).
watch(error, (now) => emit("error", now), { immediate: true });

// Re-read whenever the overview's own state changes (a section approved, a draft finished).
watch(
  () => [props.period, props.refreshKey],
  (_now, _before, onCleanup) => {
    let live = true;
    onCleanup(() => (live = false));
    api
      .getExportStatus(props.period)
      .then((s) => live && (status.value = s))
      .catch((err: Error) => live && (error.value = err.message));
  },
  { immediate: true },
);

async function download() {
  busy.value = true;
  error.value = null;
  try {
    const { blob, name } = await api.exportWeekly(props.period);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

const waiting = computed(() => (status.value ? status.value.sections.filter((s) => s.state !== "approved") : []));
const iconOf = (state: string) => (state === "approved" ? PhCheck : state === "rejected" ? PhWarning : PhQuestion);
</script>

<template>
  <section v-if="status !== null || error" aria-labelledby="export-title" class="space-y-3 rounded-lg border bg-card p-4">
    <div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
      <div class="min-w-0 space-y-1">
        <h2 id="export-title" class="text-base font-semibold">Export weekly report</h2>
        <p class="text-sm text-muted-foreground">
          {{
            status?.ready
              ? "Every section is approved. The Word file has the six sections in the issue’s order, tables, chart placeholders and each section’s summary for the CMS."
              : `Available once every section is approved: ${waiting.length} of ${status?.sections.length ?? 6} still to go.`
          }}
        </p>
      </div>
      <Button size="lg" :disabled="!status?.ready || busy" @click="download">
        <PhDownloadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
        {{ busy ? "Preparing…" : "Export weekly report" }}
      </Button>
    </div>
    <ul v-if="status" class="flex flex-wrap gap-2">
      <li
        v-for="s in status.sections"
        :key="s.slug"
        class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium"
        :class="
          s.state === 'approved'
            ? 'border-ok/40 bg-ok/10 text-ok-fg'
            : s.state === 'rejected'
              ? 'border-flag/40 bg-flag/10 text-flag-fg'
              : 'border-dashed border-input text-muted-foreground'
        "
      >
        <component :is="iconOf(s.state)" weight="bold" class="size-3" aria-hidden="true" />
        {{ s.title }}: {{ STATE_LABEL[s.state] ?? s.state }}
      </li>
    </ul>
  </section>
</template>
