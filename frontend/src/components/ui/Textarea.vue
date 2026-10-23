<script setup lang="ts">
import { cn } from "cn";
import { useAttrs } from "vue";

defineOptions({ inheritAttrs: false });
const model = defineModel<string>({ required: true });
const attrs = useAttrs();
</script>

<template>
  <textarea
    v-model="model"
    data-slot="textarea"
    v-bind="attrs"
    :class="
      cn(
        'flex field-sizing-content min-h-8 w-full rounded-md border border-input bg-card px-3 py-1 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20',
        attrs.class as string,
      )
    "
  />
</template>
