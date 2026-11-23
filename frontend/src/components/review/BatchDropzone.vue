<script setup lang="ts">
import { PhTray } from "@phosphor-icons/vue";
import { ref } from "vue";

defineProps<{ title: string; hint: string }>();
const emit = defineEmits<{ files: [files: File[]] }>();
const dragging = ref(false);

function dropped(event: DragEvent) {
  dragging.value = false;
  const files = Array.from(event.dataTransfer?.files ?? []);
  if (files.length) emit("files", files);
}
</script>

<template>
  <div
    class="flex flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed p-4 text-center transition-colors"
    :class="dragging ? 'border-primary bg-primary/5' : 'border-border/80 bg-muted/20 hover:border-border hover:bg-muted/30'"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="dropped"
  >
    <div class="flex items-center gap-2 text-sm font-medium text-foreground">
      <PhTray class="size-4 text-muted-foreground" aria-hidden="true" />
      <span>{{ title }}</span>
    </div>
    <p class="text-xs text-muted-foreground">{{ hint }}</p>
    <slot />
  </div>
</template>
