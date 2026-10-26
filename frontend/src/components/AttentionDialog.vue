<script setup lang="ts">
import {
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
} from "reka-ui";
import { nextTick, ref, watch } from "vue";
import Button from "@/components/ui/Button.vue";
import { canShow, dialogProblem, dismiss, goTo } from "@/lib/attention";

const showable = ref(false);
// Where focus goes back on Close: what had it when the dialog opened, if it is still there and usable. A button that
// disables itself while it works (Draft) has already lost focus to the page body by then; focus then goes to the problem.
let returnTo: HTMLElement | null = null;
let showing = false;
// The dialog's problem is cleared as it closes; its target is kept for the focus that follows.
let lastTarget: string | null = null;

watch(dialogProblem, async (problem, before) => {
  if (problem && !before) returnTo = document.activeElement as HTMLElement | null;
  if (problem) lastTarget = problem.target;
  await nextTick();
  showable.value = canShow(problem);
});

// First focus: "Show me" when it is offered, else "Close". Whether it is offered is known only once the page has drawn the
// problem's sentence, a frame after the dialog opens.
const footer = ref<HTMLElement | null>(null);
async function onOpenAutoFocus(event: Event) {
  event.preventDefault();
  await new Promise((resolve) => requestAnimationFrame(resolve));
  showable.value = canShow(dialogProblem.value);
  await nextTick();
  footer.value?.querySelector<HTMLElement>(showable.value ? "[data-show-me]" : "[data-close]")?.focus();
}

function showMe() {
  showing = true;
  dismiss();
}

function onCloseAutoFocus(event: Event) {
  event.preventDefault();
  const target = lastTarget;
  if (showing) {
    showing = false;
    void goTo(target, { force: true });
  } else if (returnTo && returnTo !== document.body && returnTo.isConnected && !(returnTo as HTMLButtonElement).disabled) {
    returnTo.focus();
  } else {
    void goTo(target, { force: true });
  }
  returnTo = null;
}

const open = (next: boolean) => {
  if (!next) dismiss();
};
</script>

<template>
  <AlertDialogRoot :open="dialogProblem !== null" @update:open="open">
    <AlertDialogPortal>
      <AlertDialogOverlay
        class="fixed inset-0 isolate z-50 bg-scrim/70 duration-150 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0"
      />
      <AlertDialogContent
        class="fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 overscroll-contain rounded-lg border border-t-[3px] border-border border-t-flag bg-popover p-6 text-sm text-popover-foreground shadow-lg duration-150 outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 sm:max-w-md"
        @open-auto-focus="onOpenAutoFocus"
        @close-auto-focus="onCloseAutoFocus"
      >
        <div class="flex flex-col gap-2">
          <AlertDialogTitle class="font-heading text-lg leading-snug font-semibold">{{ dialogProblem?.headline }}</AlertDialogTitle>
          <AlertDialogDescription class="text-sm text-muted-foreground">The details are shown on the page.</AlertDialogDescription>
        </div>
        <div ref="footer" class="-mx-6 -mb-6 flex flex-col-reverse gap-2 rounded-b-lg border-t bg-muted px-6 py-4 sm:flex-row sm:justify-end">
          <AlertDialogCancel as-child>
            <Button variant="outline" data-close>Close</Button>
          </AlertDialogCancel>
          <AlertDialogAction v-if="showable" as-child>
            <Button data-show-me @click="showMe">Show me</Button>
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
