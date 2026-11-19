<script setup lang="ts">
import { PhCheck, PhDownloadSimple, PhFileXls, PhQuestion, PhWarning } from "@phosphor-icons/vue";
import { computed, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import * as api from "@/lib/api";
import { ROWS_LABEL, rowsMessage, rowsWeek } from "@/lib/rows";
import type { ExportStatus } from "@/lib/types";

const STATE_LABEL: Record<string, string> = {
  approved: "Approved",
  in_review: "In review",
  rejected: "Rejected",
  not_drafted: "Not drafted",
};

const props = defineProps<{ period: string; refreshKey: string; rows?: boolean }>();
const emit = defineEmits<{ status: [status: ExportStatus | null]; error: [message: string | null] }>();
const status = ref<ExportStatus | null>(null);
watch(status, (now) => emit("status", now), { immediate: true });
const busy = ref(false);
const busyRows = ref(false);
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

function save({ blob, name }: { blob: Blob; name: string }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function download() {
  busy.value = true;
  error.value = null;
  try {
    save(await api.exportWeekly(props.period));
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

const rowsOf = computed(() => rowsWeek(props.period));

async function downloadRows() {
  if (!rowsOf.value) return;
  busyRows.value = true;
  error.value = null;
  try {
    save(await api.exportWeeklyRows(rowsOf.value));
  } catch (err) {
    error.value = rowsMessage(err instanceof api.ApiError ? err.status : null, (err as Error).message);
  } finally {
    busyRows.value = false;
  }
}

const waiting = computed(() => (status.value ? status.value.sections.filter((s) => s.state !== "approved") : []));
const iconOf = (state: string) => (state === "approved" ? PhCheck : state === "rejected" ? PhWarning : PhQuestion);
</script>

<template>
  <section v-if="status !== null || error" aria-labelledby="export-title" class="space-y-3.5 rounded-xl border border-border bg-card p-4.5 shadow-xs">
    <div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
      <div class="min-w-0 space-y-1">
        <h2 id="export-title" class="panel-title">Export weekly report</h2>
        <p class="text-sm leading-relaxed text-muted-foreground">
          {{
            status?.ready
              ? "Every section is approved. The Word file has the five sections in the issue’s order, tables, chart placeholders and each section’s summary for the CMS."
              : `Available once every section is approved: ${waiting.length} of ${status?.sections.length ?? 6} still to go.`
          }}
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button v-if="rows" variant="outline" size="lg" :disabled="!rowsOf || busyRows" @click="downloadRows">
          <PhFileXls weight="bold" data-icon="inline-start" aria-hidden="true" />
          {{ busyRows ? "Preparing…" : ROWS_LABEL }}
        </Button>
        <Button size="lg" :disabled="!status?.ready || busy" :class="status?.ready && 'brand-dot font-semibold'" @click="download">
          <PhDownloadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
          {{ busy ? "Preparing…" : "Export weekly report" }}
        </Button>
      </div>
    </div>
    <ul v-if="status" class="flex flex-wrap gap-2">
      <li
        v-for="s in status.sections"
        :key="s.slug"
        class="inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium transition-colors"
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
