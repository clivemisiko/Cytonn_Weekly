<script setup lang="ts">
import { DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from "reka-ui";
import { computed, ref } from "vue";
import Button from "@/components/ui/Button.vue";
import { plural } from "@/lib/format";
import type { Decision, Review } from "@/lib/types";

// The approval dialog only opens when the section has flagged items; its body names them (see `flagged`).
const COPY: Record<Decision, { title: string; body: string; confirm: string }> = {
  approved: {
    title: "Approve with flagged items?",
    body: "Every value is accepted as drafted. This is recorded once and cannot be changed.",
    confirm: "Approve anyway",
  },
  rejected: {
    title: "Reject this section?",
    body: "Rejecting this section locks the current draft as rejected. To revise this section later, a new draft run will need to be started.",
    confirm: "Reject",
  },
};

const props = defineProps<{ review: Review; deciding: boolean; onDecide: (decision: Decision) => Promise<boolean> }>();
const emit = defineEmits<{ close: [] }>();

const asking = ref<Decision | null>(null);
// The dialog keeps its words while it fades out after `asking` is cleared.
const last = ref<Decision>("approved");
const decided = computed(() => props.review.decision !== null);
const canApprove = computed(() => props.review.is_approvable && !decided.value);
const flagged = computed(() => props.review.review_items.filter((i) => i.status === "flagged"));

function approve() {
  if (flagged.value.length) ask("approved");
  else void props.onDecide("approved");
}

function ask(decision: Decision) {
  last.value = decision;
  asking.value = decision;
}

async function confirm() {
  if (!asking.value) return;
  await props.onDecide(asking.value);
  asking.value = null;
}

function setOpen(open: boolean) {
  if (!open && !props.deciding) asking.value = null;
}
</script>

<template>
  <div role="group" aria-label="Decision">
    <div v-if="decided" class="rise-in flex flex-wrap items-center gap-3 lg:justify-end">
      <Button variant="outline" @click="emit('close')">Back to all sections</Button>
    </div>
    <div v-else class="flex items-center gap-x-4 lg:justify-end">
      <p class="order-last max-w-64 min-w-0 text-xs text-muted-foreground lg:order-first lg:text-right">
        <span class="hidden lg:inline">One decision for the whole section. </span>Once recorded, it cannot be changed.
      </p>
      <div class="flex items-center gap-3">
        <Button size="lg" :disabled="!canApprove || deciding" @click="approve">{{ deciding && !asking ? "Recording…" : "Approve" }}</Button>
        <Button size="lg" variant="outline" :disabled="deciding" @click="ask('rejected')">Reject</Button>
      </div>
    </div>

    <DialogRoot :open="asking !== null" @update:open="setOpen">
      <DialogPortal>
        <DialogOverlay
          data-slot="dialog-overlay"
          class="fixed inset-0 isolate z-50 bg-scrim/70 duration-150 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0"
        />
        <DialogContent
          data-slot="dialog-content"
          class="fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 overscroll-contain rounded-lg border border-t-[3px] border-border border-t-primary bg-popover p-6 text-sm text-popover-foreground shadow-lg duration-150 outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 sm:max-w-md"
        >
          <div data-slot="dialog-header" class="flex flex-col gap-2">
            <DialogTitle data-slot="dialog-title" class="font-heading text-lg leading-snug font-semibold">{{ COPY[last].title }}</DialogTitle>
            <DialogDescription as="div" data-slot="dialog-description" class="space-y-2 text-sm text-muted-foreground">
              <template v-if="last === 'approved'">
                <p>This section has {{ plural(flagged.length, "flagged item") }}:</p>
                <ul class="list-disc space-y-1 pl-5 [overflow-wrap:anywhere]">
                  <li v-for="i in flagged.slice(0, 3)" :key="i.index">{{ i.ref }}</li>
                  <li v-if="flagged.length > 3">and {{ flagged.length - 3 }} more</li>
                </ul>
              </template>
              <p>{{ COPY[last].body }}</p>
            </DialogDescription>
          </div>
          <div data-slot="dialog-footer" class="-mx-6 -mb-6 flex flex-col-reverse gap-2 rounded-b-lg border-t bg-muted px-6 py-4 sm:flex-row sm:justify-end">
            <Button variant="outline" :disabled="deciding" @click="asking = null">Cancel</Button>
            <Button :disabled="deciding" :variant="last === 'rejected' ? 'destructive' : 'default'" @click="confirm">
              {{ deciding ? "Recording…" : COPY[last].confirm }}
            </Button>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  </div>
</template>
