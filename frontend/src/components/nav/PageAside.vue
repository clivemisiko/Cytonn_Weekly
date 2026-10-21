<script setup lang="ts">
import { PhCaretDoubleLeft, PhCaretDoubleRight } from "@phosphor-icons/vue";

/**
 * The side panel of a screen laid out by PageGrid. From 1100px wide it is a column on the right with a hairline on its
 * left; below that it follows the screen's content, as wide as that content. `sticky` makes it stay under the top bar
 * and scroll by itself (for a short panel); a tall one is left in the page's flow. `foldable` adds the fold button (a
 * panel that holds something a person must not miss is not given one), and `open` is the PageGrid's state. Its body is a
 * container, so what is inside lays out by the panel's own width, not the window's.
 * `first` says it comes before the content in the page's order (the rule that sets it off stacked is then below it).
 * `title` names the landmark; `hideTitle` keeps it for a screen reader when the panel's content has its own heading.
 */
defineProps<{ title?: string; hideTitle?: boolean; foldable?: boolean; open: boolean; sticky: boolean; first?: boolean }>();
const emit = defineEmits<{ toggle: [] }>();
</script>

<template>
  <aside
    :aria-label="title"
    class="min-w-0 max-[1099px]:mx-auto max-[1099px]:w-full min-[1100px]:self-start min-[1100px]:border-l"
    :class="[
      // Stacked, a rule sets the panel off from the content: below it when it comes first, above it when it comes after.
      first ? 'max-[1099px]:border-b max-[1099px]:pb-6' : 'max-[1099px]:border-t max-[1099px]:pt-6',
      sticky &&
        'min-[1100px]:sticky min-[1100px]:top-[calc(var(--topbar-h)+var(--ribbon-h,0rem)+1.5rem)] min-[1100px]:max-h-[calc(100dvh-var(--topbar-h)-var(--ribbon-h,0rem)-3rem)] min-[1100px]:overflow-x-hidden min-[1100px]:overflow-y-auto',
      open ? 'min-[1100px]:pl-6' : 'min-[1100px]:pl-2',
    ]"
  >
    <div v-if="foldable || !hideTitle" class="flex items-center justify-between gap-2 pb-4">
      <h2 class="eyebrow" :class="[!open && 'min-[1100px]:sr-only', hideTitle && 'sr-only']">{{ title }}</h2>
      <button
        v-if="foldable"
        type="button"
        class="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-[1099px]:hidden"
        :aria-expanded="open"
        :aria-label="open ? `Hide ${title}` : `Show ${title}`"
        :title="open ? `Hide ${title}` : `Show ${title}`"
        @click="emit('toggle')"
      >
        <component :is="open ? PhCaretDoubleRight : PhCaretDoubleLeft" weight="bold" class="size-4" aria-hidden="true" />
      </button>
    </div>
    <div class="@container space-y-4" :class="!open && 'min-[1100px]:hidden'">
      <slot />
    </div>
  </aside>
</template>
