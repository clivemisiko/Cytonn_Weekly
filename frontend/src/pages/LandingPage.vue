<script setup lang="ts">
import { PhArrowRight, PhCheckCircle, PhFileDoc, PhFiles } from "@phosphor-icons/vue";
import { cn } from "cn";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { buttonVariants } from "@/components/ui/button";
import { BACK_NONE, useBack } from "@/lib/nav";
import { SSO_ENABLED } from "@/lib/sso";

const props = defineProps<{ displayName?: string }>();

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

// The greeting by the viewer's own clock, read once the page is live in the browser: never a wrong greeting.
const greeting = ref<string | null>(null);
onMounted(() => (greeting.value = greetingFor(new Date().getHours())));
const hello = computed(() => (greeting.value ? (props.displayName ? `${greeting.value}, ${props.displayName}. ` : `${greeting.value}. `) : ""));

useBack(BACK_NONE); // the start screen: there is nowhere to go back to, so the bar's Back is disabled

// Seven blocks, 60ms apart, 320ms each: the last one lands at 680ms. (Reduced motion cuts it to nothing in styles.css.)
const rise = (order: number) => ({ animationDelay: `${order * 60}ms` });
</script>

<template>
  <main id="main" tabindex="-1" class="px-4 pt-10 pb-20 sm:px-6 sm:pt-16">
    <!-- One card on the page, as every screen's content is a white card on the pale ground: the title block, the welcome, the
         status, the two ways in and the notice that nothing here is protected. -->
    <div class="mx-auto w-full max-w-xl space-y-6 rounded-xl border border-border bg-card p-6 shadow-sm sm:p-9 sm:space-y-7">
      <div class="rise-slow" :style="rise(0)">
        <p class="eyebrow flex items-center gap-2">
          <span aria-hidden="true" class="brand-dot size-2 rounded-full bg-primary" />
          Cytonn Weekly
        </p>
        <h1 class="mt-2 text-2xl font-bold tracking-tight text-foreground sm:text-3xl">Report generator</h1>
      </div>

      <div class="rise-slow border-t pt-6" :style="rise(1)">
        <h2 class="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">{{ hello }}Welcome to Cytonn Weekly.</h2>
      </div>

      <div class="rise-slow" :style="rise(2)">
        <p class="max-w-[60ch] text-base leading-relaxed text-muted-foreground">
          Your drafting assistant for the weekly report. It gathers the figures, drafts each section, and checks every figure
          against its source before a person approves anything.
        </p>
        <!-- Feature highlights capsule grid -->
        <div class="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-3" aria-hidden="true">
          <div class="flex items-center gap-2 rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-xs font-medium text-foreground">
            <PhFiles class="size-4 shrink-0 text-muted-foreground" />
            <span>6 Report sections</span>
          </div>
          <div class="flex items-center gap-2 rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-xs font-medium text-foreground">
            <PhCheckCircle class="size-4 shrink-0 text-ok-fg" />
            <span>Source verified</span>
          </div>
          <div class="flex items-center gap-2 rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-xs font-medium text-foreground">
            <PhFileDoc class="size-4 shrink-0 text-muted-foreground" />
            <span>Word .docx export</span>
          </div>
        </div>
      </div>

      <div class="rise-slow" :style="rise(3)">
        <div class="flex items-center gap-3 rounded-lg border border-border/70 bg-muted/30 px-3.5 py-2.5">
          <span class="ready-dot" aria-hidden="true" />
          <p role="status" class="text-sm font-medium text-foreground">
            Ready. Nothing is drafted until you ask.
          </p>
        </div>
      </div>

      <div class="rise-slow space-y-2 border-t pt-6" :style="rise(4)">
        <Button size="lg" class="w-full sm:w-auto" :disabled="!SSO_ENABLED" :aria-describedby="SSO_ENABLED ? undefined : 'sso-state'">
          Sign in with Cytonn SSO
        </Button>
        <p v-if="!SSO_ENABLED" id="sso-state" class="text-xs text-muted-foreground">Not connected yet.</p>
      </div>

      <div class="rise-slow" :style="rise(5)">
        <RouterLink
          to="/overview"
          data-slot="button"
          :class="cn(buttonVariants({ size: 'lg', variant: 'outline' }), 'w-full gap-2 font-medium hover:border-foreground/30 sm:w-auto')"
        >
          <span>Continue without signing in</span>
          <PhArrowRight class="size-4" aria-hidden="true" />
        </RouterLink>
      </div>

      <div class="rise-slow" :style="rise(6)">
        <Notice tone="info">
          Sign-in with Cytonn SSO is not connected yet. Until it is, this tool has no sign-in and should only be used by the
          team. Draft output is a first version for human review.
        </Notice>
      </div>
    </div>
  </main>
</template>
