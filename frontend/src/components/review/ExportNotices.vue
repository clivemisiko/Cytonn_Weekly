<script setup lang="ts">
import { computed } from "vue";
import { exportChartsNote } from "@/lib/charts";
import type { ExportStatus } from "@/lib/types";
import Notice from "./Notice.vue";

const props = defineProps<{ status: ExportStatus | null; error?: string | null }>();
const charts = computed(() => exportChartsNote(props.status?.charts_missing ?? 0));
</script>

<template>
  <Notice v-if="status?.is_dev_draft" quiet role="alert">
    Export Notice: This document contains test content ({{ status.dev_sections.join(", ") }}) and includes a developer watermark on every page. It cannot be circulated or published externally.
  </Notice>
  <Notice v-if="charts" tone="info" quiet role="status">{{ charts }}</Notice>
  <!-- The export's error, where a failed export's "Show me" goes (lib/attention.ts). -->
  <div v-if="error" data-attention="export-bar">
    <Notice role="alert" data-problem class="font-medium">{{ error }}</Notice>
  </div>
</template>
