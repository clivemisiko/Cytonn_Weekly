<script setup lang="ts">
import { PhArrowRight, PhListBullets } from "@phosphor-icons/vue";
import { cn } from "cn";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import CytonnMark from "@/components/brand/CytonnMark.vue";
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
  <main id="main" tabindex="-1" class="cw-skin min-h-[calc(100dvh-var(--topbar-h))] bg-card px-4 pt-6 pb-6 sm:px-6">
    <!-- The wordmark (with the page's h1), then the centred welcome, what it does, the two ways in and the notice. -->
    <div class="mx-auto flex w-full max-w-4xl flex-col items-center gap-6 text-center">
      <div class="rise-slow flex items-center gap-2 self-start text-left text-cw-brand" :style="rise(0)">
        <CytonnMark :size="44" />
        <div class="leading-none">
          <p class="text-2xl font-bold tracking-tight">Cytonn Weekly</p>
          <h1 class="mt-1 text-xs italic">Report generator</h1>
        </div>
      </div>

      <div class="rise-slow flex flex-col items-center gap-4 pt-6" :style="rise(1)">
        <CytonnMark :size="96" />
        <h2 class="text-2xl font-normal tracking-tight text-cw-accent">{{ hello }}Welcome to Cytonn Weekly.</h2>
        <p class="max-w-[40rem] text-lg text-muted-foreground">
          Your drafting assistant for the weekly report. It gathers the figures, drafts each section, and checks every figure
          against its source before a person approves anything.
        </p>
      </div>

      <section class="rise-slow flex flex-col items-center gap-4" :style="rise(2)" aria-labelledby="landing-does">
        <h3 id="landing-does" class="flex items-center gap-3 text-sm font-bold text-foreground">
          <PhListBullets class="size-6" aria-hidden="true" />
          What it does
        </h3>
        <ul class="flex flex-wrap justify-center gap-4">
          <!-- Five: SECTIONS in backend/src/cytonn_weekly/report_sections.py (Company Updates is written by the CT team, not drafted). -->
          <li class="flex min-h-16 items-center rounded-sm bg-cw-chip px-3 py-2 text-left text-sm text-foreground">5 weekly report sections</li>
          <li class="flex min-h-16 items-center rounded-sm bg-cw-chip px-3 py-2 text-left text-sm text-foreground">Figures checked against the source</li>
          <li class="flex min-h-16 items-center rounded-sm bg-cw-chip px-3 py-2 text-left text-sm text-foreground">Word .docx export</li>
        </ul>
      </section>

      <div class="rise-slow flex flex-wrap items-start justify-center gap-4" :style="rise(3)">
        <div class="flex flex-col items-center gap-1.5">
          <Button size="lg" class="h-13 rounded-full px-7" :disabled="!SSO_ENABLED" :aria-describedby="SSO_ENABLED ? undefined : 'sso-state'">
            Sign in with Cytonn SSO
          </Button>
          <p v-if="!SSO_ENABLED" id="sso-state" class="text-xs text-muted-foreground">Not connected yet.</p>
        </div>
        <RouterLink
          to="/chat"
          data-slot="button"
          :class="cn(buttonVariants({ size: 'lg' }), 'h-13 gap-2.5 rounded-full bg-cw-button px-7 font-semibold text-cw-button-fg hover:bg-cw-button hover:opacity-90')"
        >
          <span>Continue without signing in</span>
          <PhArrowRight class="size-4" weight="bold" aria-hidden="true" />
        </RouterLink>
      </div>

      <p class="rise-slow mt-6 max-w-[47.5rem] rounded-3xl bg-cw-bubble px-5 py-3 text-xs text-foreground" :style="rise(4)">
        This tool has no sign-in and should only be used by the team. All generated drafts are preliminary and require human analyst review.
      </p>
    </div>
  </main>
</template>
