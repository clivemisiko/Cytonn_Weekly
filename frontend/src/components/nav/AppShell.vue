<script setup lang="ts">
import DevRibbon from "@/components/review/DevRibbon.vue";
import { shell } from "@/lib/shell";
import SideRail from "./SideRail.vue";
import TopBar from "./TopBar.vue";

const ribbon = shell.ribbon;
</script>

<template>
  <!-- The rail runs the full height beside the top bar, the ribbon and the page; on a phone it is a drawer under the top bar. -->
  <div class="flex items-start" :style="{ '--ribbon-h': ribbon ? '1.75rem' : '0rem' }">
    <SideRail />
    <div class="min-w-0 flex-1">
      <TopBar />
      <DevRibbon v-if="ribbon" :label="ribbon" />
      <slot />
    </div>
  </div>
</template>
