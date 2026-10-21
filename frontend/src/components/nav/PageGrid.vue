<script setup lang="ts">
import { computed, ref, useSlots } from "vue";
import { readPanelOpen, writePanelOpen } from "@/lib/panel";
import PageAside from "./PageAside.vue";

/**
 * A screen's content column (the `default` slot, centred, at most 46rem wide or, with `wideBody`, 64rem) and, optionally,
 * a side panel beside it (the `aside` slot, see PageAside.vue). From 1100px wide the panel is on the right: a quarter of
 * the window (20 to 28rem). Below 1100px it is not
 * beside anything: it follows the content, or comes first with `asideFirst` (the order of the page's DOM and of its tab
 * stops: a panel of inputs to upload before the form that uses them). `sticky` keeps a short panel under the top bar; a tall
 * one is left in the flow. When `storageKey` is given the panel can be folded to a 3rem strip and the choice is remembered
 * in this browser (lib/panel.ts); a panel that holds something a person must not miss is never given one. The content
 * column is a container too, so what is in it lays out by its own width, not the window's.
 */
const props = withDefaults(
  defineProps<{ asideTitle?: string; hideTitle?: boolean; storageKey?: string; asideFirst?: boolean; sticky?: boolean; wideBody?: boolean }>(),
  { sticky: true },
);
const slots = useSlots();
const open = ref(props.storageKey ? readPanelOpen(props.storageKey) : true);

function toggle() {
  open.value = !open.value;
  if (props.storageKey) writePanelOpen(props.storageKey, open.value);
}

const columns = computed(() => {
  if (!slots.aside) return "";
  if (!open.value) return "min-[1100px]:grid-cols-[minmax(0,1fr)_3rem]";
  return "min-[1100px]:grid-cols-[minmax(0,1fr)_clamp(20rem,25vw,28rem)]";
});
// The same width cap for the content and, when the panel is stacked under (or over) it, for the panel.
const cap = computed(() => (props.wideBody ? "max-w-5xl" : "max-w-184"));
const stackedCap = computed(() => (props.wideBody ? "max-[1099px]:max-w-5xl" : "max-[1099px]:max-w-184"));
</script>

<template>
  <div class="grid w-full gap-8 px-4 pt-6 pb-16 sm:px-6" :class="columns">
    <PageAside
      v-if="slots.aside && asideFirst"
      first
      :title="asideTitle"
      :hide-title="hideTitle"
      :foldable="!!storageKey"
      :open="open"
      :sticky="sticky"
      class="min-[1100px]:col-start-2 min-[1100px]:row-start-1"
      :class="stackedCap"
      @toggle="toggle"
    >
      <slot name="aside" />
    </PageAside>
    <div class="@container mx-auto w-full min-w-0 min-[1100px]:col-start-1 min-[1100px]:row-start-1" :class="cap">
      <slot />
    </div>
    <PageAside
      v-if="slots.aside && !asideFirst"
      :title="asideTitle"
      :hide-title="hideTitle"
      :foldable="!!storageKey"
      :open="open"
      :sticky="sticky"
      class="min-[1100px]:col-start-2 min-[1100px]:row-start-1"
      :class="stackedCap"
      @toggle="toggle"
    >
      <slot name="aside" />
    </PageAside>
  </div>
</template>
