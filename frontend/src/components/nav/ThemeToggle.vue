<script setup lang="ts">
import { PhMonitor, PhMoon, PhSun } from "@phosphor-icons/vue";
import { RadioGroupItem, RadioGroupRoot } from "reka-ui";
import { onUnmounted, ref } from "vue";
import { THEMES, type ThemeChoice, currentTheme, setTheme, subscribeTheme } from "@/lib/theme";

const OPTIONS = {
  light: { label: "Light", icon: PhSun },
  dark: { label: "Dark", icon: PhMoon },
  system: { label: "System", icon: PhMonitor },
} as const;

// The page's own attribute is the truth (the inline script may have set it before this ran).
const choice = ref<ThemeChoice>(currentTheme());
onUnmounted(subscribeTheme(() => (choice.value = currentTheme())));
</script>

<template>
  <div class="flex items-center gap-2">
    <span class="hidden text-xs text-band-muted sm:inline" aria-hidden="true">
      Theme: <span class="font-semibold text-band-foreground">{{ OPTIONS[choice].label }}</span>
    </span>
    <RadioGroupRoot
      :model-value="choice"
      orientation="horizontal"
      :aria-label="`Theme: ${OPTIONS[choice].label}`"
      class="flex items-center"
      @update:model-value="(next) => setTheme(next as ThemeChoice)"
    >
      <RadioGroupItem
        v-for="theme in THEMES"
        :key="theme"
        :value="theme"
        :aria-label="`${OPTIONS[theme].label} theme`"
        :title="`${OPTIONS[theme].label} theme`"
        class="group grid size-10 place-items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-band-muted focus-visible:ring-inset"
      >
        <span
          class="grid size-8 place-items-center rounded-md border transition-colors duration-150"
          :class="
            theme === choice
              ? 'border-band-muted bg-band-foreground/15 text-band-foreground'
              : 'border-transparent text-band-muted group-hover:bg-band-foreground/10 group-hover:text-band-foreground'
          "
        >
          <component :is="OPTIONS[theme].icon" :weight="theme === choice ? 'fill' : 'regular'" class="size-4" aria-hidden="true" />
        </span>
      </RadioGroupItem>
    </RadioGroupRoot>
  </div>
</template>
