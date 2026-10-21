<script setup lang="ts">
import DevRibbon from "@/components/review/DevRibbon.vue";
import { shell } from "@/lib/shell";
import SideRail from "./SideRail.vue";

/**
 * Everything under the top bar on every screen but the start page: the dev-mode ribbon (when the screen on view is a
 * dev-mode one), then the rail on the left and the screen beside it. The page scrolls as a whole, so the top bar, the
 * ribbon and the rail all stick where they are. The screen says whether the ribbon shows (lib/shell.ts), since only
 * the screen knows whether what it holds was drafted by the local model.
 */
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
