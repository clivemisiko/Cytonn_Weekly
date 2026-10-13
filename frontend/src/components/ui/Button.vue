<script setup lang="ts">
import { cn } from "cn";
import { useAttrs } from "vue";
import { type ButtonProps, buttonVariants } from "./button";

defineOptions({ inheritAttrs: false });
const props = withDefaults(defineProps<{ variant?: ButtonProps["variant"]; size?: ButtonProps["size"] }>(), {
  variant: "default",
  size: "default",
});
const attrs = useAttrs();
</script>

<template>
  <button
    type="button"
    data-slot="button"
    :data-variant="props.variant"
    :data-size="props.size"
    v-bind="attrs"
    :class="cn(buttonVariants({ variant: props.variant, size: props.size }), attrs.class as string)"
  >
    <slot />
  </button>
</template>
