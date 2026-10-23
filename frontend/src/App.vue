<script setup lang="ts">
import { RouterView } from "vue-router";
import AttentionDialog from "@/components/AttentionDialog.vue";
import AppShell from "@/components/nav/AppShell.vue";
import TopBar from "@/components/nav/TopBar.vue";
import { HOME } from "@/lib/nav";
</script>

<template>
  <a
    href="#main"
    class="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
  >
    Skip to main content
  </a>
  <TopBar />
  <!-- Keyed on the path: another run is a fresh run view, while the overview's query can change under one page.
       The start page stands alone; every other screen sits in the shell (the dev ribbon and the rail). -->
  <RouterView v-slot="{ Component, route }">
    <AppShell v-if="route.path !== HOME">
      <component :is="Component" :key="route.path" />
    </AppShell>
    <component :is="Component" v-else :key="route.path" />
  </RouterView>
  <!-- The one dialog for an action that failed as a whole (lib/attention.ts); portalled to the body. -->
  <AttentionDialog />
</template>
