<script setup lang="ts">
import { DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from "reka-ui";
import Button from "@/components/ui/Button.vue";

/**
 * "Draft <section> again?": asked before a section that already has a review is drafted over. It says what happens to
 * the earlier review and to the new draft (lib/redraft.ts); nothing here changes either.
 */
defineProps<{ open: boolean; title: string; notes: string[]; confirmLabel: string }>();
const emit = defineEmits<{ confirm: []; cancel: [] }>();
</script>

<template>
  <DialogRoot :open="open" @update:open="(next) => !next && emit('cancel')">
    <DialogPortal>
      <DialogOverlay
        data-slot="dialog-overlay"
        class="fixed inset-0 isolate z-50 bg-band/70 duration-150 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0"
      />
      <DialogContent
        data-slot="dialog-content"
        class="fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 overscroll-contain rounded-lg border border-t-[3px] border-border border-t-primary bg-popover p-6 text-sm text-popover-foreground shadow-lg duration-150 outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 sm:max-w-md"
      >
        <div data-slot="dialog-header" class="flex flex-col gap-2">
          <DialogTitle data-slot="dialog-title" class="font-heading text-lg leading-snug font-semibold">{{ title }}</DialogTitle>
          <DialogDescription as="div" data-slot="dialog-description" class="space-y-2 text-sm text-muted-foreground">
            <p v-for="note in notes" :key="note">{{ note }}</p>
          </DialogDescription>
        </div>
        <div data-slot="dialog-footer" class="-mx-6 -mb-6 flex flex-col-reverse gap-2 rounded-b-lg border-t bg-muted px-6 py-4 sm:flex-row sm:justify-end">
          <Button variant="outline" @click="emit('cancel')">Cancel</Button>
          <Button @click="emit('confirm')">{{ confirmLabel }}</Button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
