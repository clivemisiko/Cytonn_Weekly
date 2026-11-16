<script setup lang="ts">
import { computed, ref, useSlots } from "vue";
import PageAside from "./PageAside.vue";

withDefaults(
  defineProps<{ asideTitle?: string; hideTitle?: boolean; storageKey?: string; asideFirst?: boolean; sticky?: boolean; wideBody?: boolean }>(),
  { sticky: true },
);
const slots = useSlots();
const open = ref(true);

function toggle() {
  open.value = !open.value;
}

// From 1100px the panel is a rail running the page's full height on the right, so the grid drops its own padding there
// and the feed carries it instead.
const columns = computed(() => {
  if (!slots.aside) return "";
  // Important: Tailwind orders the arbitrary 1100px variant before sm: and lg:, which would otherwise win.
  const rail = "min-[1100px]:gap-0! min-[1100px]:p-0! min-[1100px]:min-h-[calc(100dvh-var(--topbar-h)-var(--ribbon-h,0rem))]";
  if (!open.value) return `${rail} min-[1100px]:grid-cols-[minmax(0,1fr)_3rem]`;
  return `${rail} min-[1100px]:grid-cols-[minmax(0,1fr)_clamp(20rem,25vw,28rem)]`;
});
</script>

<template>
  <div class="grid w-full gap-4 px-4 pt-4 pb-16 sm:px-6 lg:gap-5" :class="columns">
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
    <div class="@container w-full min-w-0 min-[1100px]:col-start-1 min-[1100px]:row-start-1" :class="slots.aside && 'min-[1100px]:px-6 min-[1100px]:pt-5 min-[1100px]:pb-16'">
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
