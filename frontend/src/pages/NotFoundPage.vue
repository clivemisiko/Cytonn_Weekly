<script setup lang="ts">
import PageGrid from "@/components/nav/PageGrid.vue";
import Masthead from "@/components/review/Masthead.vue";
import { shell } from "@/lib/shell";

shell.invalidate(); // the rail knows no section's state here
</script>

<template>
  <main id="main" tabindex="-1">
    <Masthead wide title="Page not found" />
    <PageGrid>
      <div class="rounded-lg border bg-card p-6">
        <p class="text-sm">This page could not be found.</p>
      </div>
    </PageGrid>
  </main>
</template>
