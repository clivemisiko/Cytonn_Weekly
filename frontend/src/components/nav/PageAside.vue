<script setup lang="ts">
import { PhCaretDoubleLeft, PhCaretDoubleRight } from "@phosphor-icons/vue";

defineProps<{ title?: string; hideTitle?: boolean; foldable?: boolean; open: boolean; sticky: boolean; first?: boolean }>();
const emit = defineEmits<{ toggle: [] }>();
</script>

<template>
  <!-- From 1100px a rail: the full height of the page, a hairline on its left, its own fill. When it sticks, its inner
       column does, so the rail itself still runs to the foot of the page. -->
  <aside
    :aria-label="title"
    class="min-w-0 max-[1099px]:mx-auto max-[1099px]:w-full min-[1100px]:self-stretch min-[1100px]:border-l min-[1100px]:bg-card"
    :class="first ? 'max-[1099px]:border-b max-[1099px]:pb-6' : 'max-[1099px]:border-t max-[1099px]:pt-6'"
  >
    <div
      class="min-[1100px]:pt-5 min-[1100px]:pb-8"
      :class="[
        open ? 'min-[1100px]:px-5' : 'min-[1100px]:px-2',
        sticky &&
          'min-[1100px]:sticky min-[1100px]:top-[calc(var(--topbar-h)+var(--ribbon-h,0rem)+var(--bar-extra,0rem))] min-[1100px]:max-h-[calc(100dvh-var(--topbar-h)-var(--ribbon-h,0rem)-var(--bar-extra,0rem))] min-[1100px]:overflow-x-hidden min-[1100px]:overflow-y-auto',
      ]"
    >
      <div v-if="foldable || !hideTitle" class="flex items-center justify-between gap-2 pb-4">
        <h2 class="panel-title" :class="[!open && 'min-[1100px]:sr-only', hideTitle && 'sr-only']">{{ title }}</h2>
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
      <div class="rail-stack @container space-y-5" :class="!open && 'min-[1100px]:hidden'">
        <slot />
      </div>
    </div>
  </aside>
</template>
