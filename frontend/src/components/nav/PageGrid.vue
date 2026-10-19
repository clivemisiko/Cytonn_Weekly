<script setup lang="ts">
import { PhCaretDoubleLeft, PhCaretDoubleRight } from "@phosphor-icons/vue";
import { ref, useSlots } from "vue";
import { readPanelOpen, writePanelOpen } from "@/lib/panel";

/**
 * A screen's centre column (the `default` slot, at most 46rem wide and centred) and, optionally, a side panel beside it
 * (the `aside` slot). From 1100px wide the panel sits to the right, as wide as a quarter of the window (20 to 28rem), sticks
 * under the top bar, and, when `storageKey` is given, can be folded to a 3rem strip (the choice is remembered in this
 * browser, see lib/panel.ts). Below 1100px it is not beside anything: it follows the centre column, always open, and the
 * fold button is not shown. A panel that holds something a person must not miss is not given a `storageKey`, so it cannot
 * be folded. The panel's body is a container, so what is inside it lays out by its own width, not the window's.
 */
const props = defineProps<{ asideTitle?: string; storageKey?: string }>();
const slots = useSlots();
const open = ref(props.storageKey ? readPanelOpen(props.storageKey) : true);

function toggle() {
  open.value = !open.value;
  if (props.storageKey) writePanelOpen(props.storageKey, open.value);
}
</script>

<template>
  <div
    class="grid w-full gap-8 px-4 pt-6 pb-16 sm:px-6"
    :class="slots.aside && (open ? 'min-[1100px]:grid-cols-[minmax(0,1fr)_clamp(20rem,25vw,28rem)]' : 'min-[1100px]:grid-cols-[minmax(0,1fr)_3rem]')"
  >
    <div class="mx-auto w-full max-w-184 min-w-0">
      <slot />
    </div>
    <aside
      v-if="slots.aside"
      :aria-label="asideTitle"
      class="min-w-0 max-[1099px]:border-t max-[1099px]:pt-6 min-[1100px]:sticky min-[1100px]:top-[calc(var(--topbar-h)+var(--ribbon-h,0rem)+1.5rem)] min-[1100px]:max-h-[calc(100dvh-var(--topbar-h)-var(--ribbon-h,0rem)-3rem)] min-[1100px]:self-start min-[1100px]:overflow-y-auto min-[1100px]:border-l min-[1100px]:pl-6"
    >
      <div class="flex items-center justify-between gap-2 pb-4">
        <h2 class="eyebrow" :class="!open && 'min-[1100px]:sr-only'">{{ asideTitle }}</h2>
        <button
          v-if="storageKey"
          type="button"
          class="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-[1099px]:hidden"
          :aria-expanded="open"
          :aria-label="open ? `Hide ${asideTitle}` : `Show ${asideTitle}`"
          :title="open ? `Hide ${asideTitle}` : `Show ${asideTitle}`"
          @click="toggle"
        >
          <component :is="open ? PhCaretDoubleRight : PhCaretDoubleLeft" weight="bold" class="size-4" aria-hidden="true" />
        </button>
      </div>
      <div class="@container space-y-4" :class="!open && 'min-[1100px]:hidden'">
        <slot name="aside" />
      </div>
    </aside>
  </div>
</template>
