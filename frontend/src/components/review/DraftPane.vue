<script setup lang="ts">
import { computed } from "vue";
import { SCOPE_LABELS, TABLE_COLUMNS, weekRange } from "@/lib/format";
import type { HighlightItem, Review, Section, StockTableItem } from "@/lib/types";
import DataTable from "./DataTable.vue";
import Markdown from "./Markdown.vue";
import Notice from "./Notice.vue";
import Numeral from "./Numeral.vue";
import PartsLine from "./PartsLine.vue";
import Warnings from "./Warnings.vue";

/** The drafted section (the weekly Digital Payments shape), for context while resolving items: highlights, the table, the outlook. */
const props = defineProps<{ review: Review; section: Section }>();
const highlights = computed(() => props.section.items.filter((i): i is HighlightItem => i.kind === "highlight"));
const table = computed(() => props.section.items.find((i): i is StockTableItem => i.kind === "stock_table"));
type Row = Record<string, unknown> & { flagged: boolean };
</script>

<template>
  <section aria-labelledby="draft-title" class="min-w-0 rounded-lg border bg-card [overflow-wrap:anywhere]">
    <div class="flex flex-col gap-3 px-4 py-4 sm:px-6">
      <h2 id="draft-title" class="text-lg font-semibold">Drafted section: {{ weekRange(section.week_start, section.week_end) }}</h2>
      <div class="space-y-2 empty:hidden">
        <Notice v-if="review.is_dev_draft && review.dev_mode_label" role="alert" class="font-semibold">{{ review.dev_mode_label }}</Notice>
        <Notice v-if="section.shortfall > 0" tone="warn" role="status" class="font-semibold">
          Only {{ section.highlights_found }} of {{ section.highlights_expected }} highlights were found this week.
        </Notice>
        <Notice v-for="(w, i) in section.warnings" :key="`${i}-${w}`" tone="warn">{{ w }}</Notice>
      </div>
    </div>

    <article v-for="item in highlights" :key="item.numeral" class="space-y-3 border-t px-4 py-6 sm:px-6" :aria-labelledby="`hl-${item.numeral}`">
      <h3 :id="`hl-${item.numeral}`" class="flex items-start gap-3 text-base font-semibold">
        <Numeral>{{ item.numeral }}</Numeral>
        <span>{{ item.headline }}</span>
      </h3>
      <Markdown class="max-w-[68ch] text-base leading-7 md:pl-11" :text="item.body_md" />
      <!-- Where a highlight came from, as one quiet line: company, search scope, domain, drafting model. -->
      <PartsLine
        :parts="[
          { text: item.company, style: 'name' },
          { text: SCOPE_LABELS[item.search_scope] ?? item.search_scope },
          { text: item.ir_domain ?? '', style: 'mono' },
          { text: `Drafted by ${item.drafted_by}`, style: 'mono' },
        ]"
      />
      <!-- Always there: hidden when empty, it still keeps the line above from being the last child. -->
        <div class="md:pl-11 empty:hidden"><Warnings :items="item.warnings" /></div>
    </article>

    <section v-if="table" class="space-y-3 border-t px-4 py-6 sm:px-6" aria-labelledby="stock-table-title">
      <h3 id="stock-table-title" class="flex items-center gap-3 text-base font-semibold">
        <Numeral>{{ table.numeral }}</Numeral>
        {{ table.title }}
      </h3>
      <DataTable id="stock" :title="table.title" :columns="TABLE_COLUMNS" :rows="table.rows as unknown as Row[]" row-key="ticker" />
      <template v-for="r in table.rows" :key="r.ticker">
        <p v-if="r.error" class="text-sm text-flag-fg">{{ r.ticker }} failed to fetch: {{ r.error }}</p>
      </template>
    </section>

    <section class="space-y-4 border-t px-4 py-6 sm:px-6" aria-label="Outlook">
      <Markdown class="max-w-[68ch] text-base leading-7" :text="section.outlook.text_md" />
      <dl class="max-w-md divide-y rounded-md border text-sm">
        <div v-for="s in section.outlook.stats" :key="s.key" class="flex items-baseline justify-between gap-6 px-3 py-2">
          <dt class="font-mono text-xs text-muted-foreground">{{ s.key }}</dt>
          <dd class="text-right font-medium">{{ s.value }}</dd>
        </div>
      </dl>
      <Warnings :items="section.outlook.warnings" />
    </section>
  </section>
</template>
