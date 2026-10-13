<script setup lang="ts">
import { RouterView } from "vue-router";
import TopBar from "@/components/nav/TopBar.vue";
</script>

<template>
  <a
    href="#main"
    class="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
  >
    Skip to main content
  </a>
  <TopBar />
  <!-- Keyed on the path: another run is a fresh run view, while the overview's query can change under one page. -->
  <RouterView v-slot="{ Component, route }">
    <component :is="Component" :key="route.path" />
  </RouterView>
</template>
