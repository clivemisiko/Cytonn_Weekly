<script setup lang="ts">
import { LONG_ID } from "@/lib/format";
import TruncatedId from "./TruncatedId.vue";

/** System-written text with any long hash inside it shown as a TruncatedId. */
defineProps<{ text: string }>();
const isId = (part: string) => LONG_ID.test(part);
</script>

<template>
  <template v-for="(part, i) in text.split(LONG_ID)" :key="i"><TruncatedId v-if="isId(part)" :value="part" /><template v-else>{{ part }}</template></template>
</template>
