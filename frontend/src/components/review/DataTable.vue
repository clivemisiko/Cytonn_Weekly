<script setup lang="ts">
defineProps<{
  id: string;
  title: string;
  columns: { key: string; label: string; numeric: boolean }[];
  rows: (Record<string, unknown> & { flagged: boolean })[];
  rowKey: string;
}>();
</script>

<template>
  <div
    role="region"
    :aria-label="`${title}, scrolls sideways on narrow screens`"
    tabindex="0"
    class="overflow-x-auto rounded-lg border border-border/80 bg-card shadow-xs focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
  >
    <table class="w-full border-collapse text-sm break-normal" :class="columns.length > 5 ? 'min-w-160' : 'min-w-120'">
      <caption class="sr-only">
        {{ title }}. Rows the checker flagged are marked in the first column.
      </caption>
      <thead>
        <tr class="border-b border-border bg-muted/70">
          <th
            v-for="c in columns"
            :key="c.key"
            scope="col"
            class="eyebrow px-3 py-2.5 align-bottom whitespace-nowrap lg:whitespace-normal"
            :class="c.numeric ? 'text-right' : 'text-left'"
          >
            {{ c.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="rows.length === 0">
          <td :colspan="columns.length" class="px-3 py-3.5 text-sm text-muted-foreground">No rows this week.</td>
        </tr>
        <tr
          v-for="row in rows"
          :key="`${id}-${String(row[rowKey])}`"
          :data-flagged="row.flagged || undefined"
          class="border-b border-border/50 transition-colors last:border-b-0 hover:bg-muted/50 data-flagged:bg-flag/10 data-flagged:font-semibold"
        >
          <td
            v-for="(c, i) in columns"
            :key="c.key"
            :translate="c.numeric ? undefined : 'no'"
            class="px-3 py-2.5 whitespace-nowrap"
            :class="[
              c.numeric ? 'text-right font-mono tabular-nums' : 'text-left',
              i === 0 && 'font-medium',
              c.key === 'ticker' && 'font-mono text-muted-foreground',
              i === 0 && row.flagged && 'shadow-[inset_6px_0_0_var(--flag)]',
            ]"
          >
            <span v-if="i === 0 && row.flagged" class="state-flagged mr-2 inline-flex align-middle"
              ><span class="glyph" title="Flagged by the checker"><span class="sr-only">Flagged: </span>!</span></span
            >{{ String(row[c.key] ?? "-") }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
