<script setup lang="ts">
import { computed } from "vue";
import { originLabel, tableOrigin } from "@/lib/analyst";
import type { AnalystTable } from "@/lib/types";
import Notice from "../Notice.vue";
import Differences from "./Differences.vue";
import OriginChip from "./OriginChip.vue";
import SourceLine from "./SourceLine.vue";

/**
 * What every typed table has around its editor: the heading with its origin chip, help and source above (TableHead in
 * analyst-panel.tsx), and the workbook reference, warnings and differences below (TableNotes). The editor is the slot.
 */
const props = defineProps<{ item: AnalystTable; count: number; typed: boolean }>();
const origin = computed(() => tableOrigin(props.item));
const rows = computed(() => `${props.count} row${props.count === 1 ? "" : "s"}`);
</script>

<template>
  <div class="space-y-2">
    <div class="space-y-1">
      <div class="flex flex-wrap items-center gap-2">
        <h4 class="text-sm font-semibold">{{ item.label }}</h4>
        <OriginChip :origin="origin">{{ originLabel(origin, item.carried, rows) }}</OriginChip>
      </div>
      <p v-if="item.help" class="max-w-[72ch] text-xs text-muted-foreground">{{ item.help }}</p>
      <SourceLine :source="item.source" :used-in="item.used_in" />
    </div>
    <slot />
    <p v-if="!typed && item.workbook_ref" class="text-xs text-muted-foreground">
      Read from <span class="font-mono">{{ item.workbook_ref }}</span>. Type here to use yours instead.
    </p>
    <p v-if="item.workbook_note && !typed" class="text-xs text-warn-fg">{{ item.workbook_note }}</p>
    <Notice v-for="w in item.warnings" :key="w" tone="warn" role="status">{{ w }}</Notice>
    <Differences :lines="item.differences" />
  </div>
</template>
