<script setup lang="ts">
import { cn } from "cn";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { buttonVariants } from "@/components/ui/button";
import { BACK_NONE, useBack } from "@/lib/nav";
import { SSO_ENABLED } from "@/lib/sso";

/**
 * The first screen: what the tool is, that it is ready, and the way in. Sign-in with Cytonn SSO is not built
 * (lib/sso.ts, backend/api/sso.py), so its button is disabled and says so, and the page states plainly that nothing
 * here is protected. `displayName` is for the signed-in name once sign-in exists; nothing passes it today.
 */
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
  <main id="main" tabindex="-1" class="px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
    <!-- One card on the page, as every screen's content is a white card on the pale ground: the title block, the welcome, the
         status, the two ways in and the notice that nothing here is protected. -->
    <div class="mx-auto w-full max-w-xl space-y-6 rounded-xl border bg-card p-6 sm:p-8">
      <div class="rise-slow" :style="rise(0)">
        <p class="eyebrow flex items-center gap-2">
          <span aria-hidden="true" class="block h-0.5 w-4 rounded-full bg-current" />
          Cytonn Weekly
        </p>
        <h1 class="mt-2 text-xl font-semibold sm:text-2xl">Report generator</h1>
      </div>

      <div class="rise-slow border-t pt-6" :style="rise(1)">
        <h2 class="text-xl font-semibold sm:text-2xl">{{ hello }}Welcome to Cytonn Weekly.</h2>
      </div>

      <div class="rise-slow" :style="rise(2)">
        <p class="max-w-[60ch] text-base text-muted-foreground">
          Your drafting assistant for the weekly report. It gathers the figures, drafts each section, and checks every figure
          against its source before a person approves anything.
        </p>
      </div>

      <div class="rise-slow" :style="rise(3)">
        <p role="status" class="flex items-center gap-3 text-sm font-medium">
          <span class="ready-dot" aria-hidden="true" />
          Ready. Nothing is drafted until you ask.
        </p>
      </div>

      <div class="rise-slow space-y-2 border-t pt-6" :style="rise(4)">
        <Button size="lg" class="w-full sm:w-auto" :disabled="!SSO_ENABLED" :aria-describedby="SSO_ENABLED ? undefined : 'sso-state'">
          Sign in with Cytonn SSO
        </Button>
        <p v-if="!SSO_ENABLED" id="sso-state" class="text-xs text-muted-foreground">Not connected yet.</p>
      </div>

      <div class="rise-slow" :style="rise(5)">
        <RouterLink to="/overview" data-slot="button" :class="cn(buttonVariants({ size: 'lg', variant: 'outline' }), 'w-full sm:w-auto')">
          Continue without signing in
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
