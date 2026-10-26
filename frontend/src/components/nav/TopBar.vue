<script setup lang="ts">
import { PhArrowLeft, PhHouse } from "@phosphor-icons/vue";
import { computed } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { HOME, mayLeave, useBackTarget } from "@/lib/nav";
import ThemeToggle from "./ThemeToggle.vue";

// One look for Home and Back: 40px tall (the touch target), text and icon in the band's ink, a visible focus ring.
const CONTROL =
  "inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold text-band-foreground outline-none transition-colors duration-150 hover:bg-band-foreground/10 focus-visible:ring-2 focus-visible:ring-band-muted focus-visible:ring-inset disabled:cursor-not-allowed disabled:text-band-muted/60 disabled:hover:bg-transparent aria-[current=page]:text-band-muted";

const router = useRouter();
const route = useRoute();
const back = useBackTarget();
const atHome = computed(() => route.path === HOME);
const backTo = computed(() => (back.value.kind === "go" || back.value.kind === "href" ? back.value.to : "Home"));

function goBack() {
  if (!mayLeave()) return;
  const target = back.value;
  if (target.kind === "go") target.go();
  else void router.push(target.kind === "href" ? target.href : HOME);
}
</script>

<template>
  <header class="sticky top-0 z-40 flex h-(--topbar-h) border-b border-band-rule bg-band text-band-foreground">
    <!-- The wordmark sits over the rail and is as wide as it is (56px from 768px, 224px from 1366px), so the top bar reads
         as the rail's header. It is text and a dot: the project has no logo. Both widths are written as min-[...px]:
         because Tailwind sorts those before the named `md:`, which would then beat the 1366px one. -->
    <p
      class="flex h-full shrink-0 items-center gap-2 px-3 text-sm font-semibold whitespace-nowrap min-[768px]:w-14 min-[768px]:justify-center min-[768px]:border-r min-[768px]:border-band-rule min-[768px]:px-0 min-[1366px]:w-56 min-[1366px]:justify-start min-[1366px]:px-4"
    >
      <span class="size-2.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
      <span class="sr-only min-[1366px]:not-sr-only">Cytonn Weekly</span>
    </p>
    <nav aria-label="App" class="flex h-full min-w-0 flex-1 items-center gap-1 px-2 sm:px-4">
      <RouterLink v-slot="{ href, navigate }" :to="HOME" custom>
        <a
          :href="href"
          aria-label="Home"
          :aria-current="atHome ? 'page' : undefined"
          :class="CONTROL"
          @click="(event) => (mayLeave() ? navigate(event) : event.preventDefault())"
        >
          <PhHouse weight="bold" class="size-4" aria-hidden="true" />
          Home
        </a>
      </RouterLink>
      <button
        type="button"
        :class="CONTROL"
        :disabled="back.kind === 'none'"
        :aria-label="back.kind === 'none' ? 'Back (this is the start screen)' : `Back to ${backTo}`"
        :title="back.kind === 'none' ? 'This is the start screen' : `Back to ${backTo}`"
        @click="goBack"
      >
        <PhArrowLeft weight="bold" class="size-4" aria-hidden="true" />
        Back
      </button>
      <div class="ml-auto">
        <ThemeToggle />
      </div>
    </nav>
  </header>
</template>
