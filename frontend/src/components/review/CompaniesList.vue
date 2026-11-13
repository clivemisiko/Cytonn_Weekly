<script setup lang="ts">
import { onMounted, ref } from "vue";
import * as api from "@/lib/api";
import type { EquitiesCompanies } from "@/lib/types";

const data = ref<EquitiesCompanies | null>(null);
const error = ref<string | null>(null);
onMounted(async () => {
  try {
    data.value = await api.getEquitiesCompanies();
  } catch (err) {
    error.value = (err as api.ApiError).message;
  }
});
</script>

<template>
  <section aria-labelledby="companies-title" class="space-y-3 rounded-lg border border-t-[3px] border-t-primary bg-card p-6">
    <div class="space-y-1">
      <h2 id="companies-title" class="text-lg font-semibold">Listed banks and insurers</h2>
      <p class="text-sm text-muted-foreground">
        Each company's own website is read for news and results dated in the report week. Only Kenyan pages are used. If a site
        cannot be read, a search limited to that site is used instead. A company whose website is still to be confirmed is not read.
      </p>
    </div>
    <p v-if="error" role="alert" class="text-sm font-medium">{{ error }}</p>
    <p v-else-if="!data" role="status" class="text-sm text-muted-foreground">Reading the list…</p>
    <ul v-else class="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2" aria-label="Companies and their website status">
      <li v-for="c in data.companies" :key="c.name" class="flex flex-wrap items-baseline justify-between gap-2 border-b py-1">
        <span>{{ c.name }} <span class="text-xs text-muted-foreground">({{ c.type }})</span></span>
        <span :class="c.set ? 'font-semibold text-ok-fg' : 'font-semibold text-warn-fg'">
          {{ c.set ? `Website set: ${c.domain}` : "Website to confirm" }}
        </span>
      </li>
    </ul>
  </section>
</template>
