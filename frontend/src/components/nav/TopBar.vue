<script setup lang="ts">
import { PhArrowLeft, PhHouse } from "@phosphor-icons/vue";
import { computed } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { HOME, mayLeave, useBackTarget } from "@/lib/nav";
import ThemeToggle from "./ThemeToggle.vue";

// One look for Home and Back: 40px tall (the touch target), text and icon in the band's ink, a visible focus ring.
const CONTROL =
  "inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold text-band-foreground outline-none transition-colors duration-150 hover:bg-band-foreground/10 focus-visible:ring-2 focus-visible:ring-band-muted focus-visible:ring-inset disabled:cursor-not-allowed disabled:text-band-muted/60 disabled:hover:bg-transparent aria-[current=page]:text-band-muted";

/**
 * The one bar at the top of every page, always in view while the page scrolls: Home, Back and the theme. It is the
 * band's colour, so it reads as the top edge of the masthead under it, and it is 44px tall (--topbar-h in
 * styles.css), which everything that sticks below it offsets by.
 *
 * Home always goes to the start screen. Back goes where the page on screen says (lib/nav.ts): its own parent, or
 * Home when it has none; on the start screen it is disabled, not hidden. Neither ever leaves the app. Both ask first
 * when the page holds unsaved edits.
 */
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
  <header class="sticky top-0 z-40 h-(--topbar-h) border-b border-band-rule bg-band text-band-foreground">
    <nav aria-label="App" class="mx-auto flex h-full w-full max-w-375 items-center gap-1 px-2 sm:px-4">
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
