<script setup lang="ts">
import { computed, ref, useSlots } from "vue";
import { readPanelOpen, writePanelOpen } from "@/lib/panel";
import PageAside from "./PageAside.vue";

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
