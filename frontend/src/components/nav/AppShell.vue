<script setup lang="ts">
import DevRibbon from "@/components/review/DevRibbon.vue";
import { shell } from "@/lib/shell";
import SideRail from "./SideRail.vue";

const ribbon = shell.ribbon;
</script>

<template>
  <DevRibbon v-if="ribbon" :label="ribbon" />
  <div class="flex items-start" :style="{ '--ribbon-h': ribbon ? '1.75rem' : '0rem' }">
    <SideRail />
    <div class="min-w-0 flex-1">
      <slot />
    </div>
  </div>
</template>
