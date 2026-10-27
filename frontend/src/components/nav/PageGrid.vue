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

// Responsive column template for desktop: keeps aside panel width constrained while content expands fluidly
const columns = computed(() => {
  if (!slots.aside) return "";
  if (!open.value) return "min-[1100px]:grid-cols-[minmax(0,1fr)_3rem]";
  return "min-[1100px]:grid-cols-[minmax(0,1fr)_clamp(20rem,25vw,28rem)]";
});
</script>

<template>
  <div class="grid w-full gap-4 px-3 pt-4 pb-16 sm:px-5 lg:gap-5" :class="columns">
    <PageAside
      v-if="slots.aside && asideFirst"
      first
      :title="asideTitle"
      :hide-title="hideTitle"
      :foldable="!!storageKey"
      :open="open"
      :sticky="sticky"
      class="min-[1100px]:col-start-2 min-[1100px]:row-start-1"
      @toggle="toggle"
    >
      <slot name="aside" />
    </PageAside>
    <div class="@container w-full min-w-0 min-[1100px]:col-start-1 min-[1100px]:row-start-1">
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
      @toggle="toggle"
    >
      <slot name="aside" />
    </PageAside>
  </div>
</template>
