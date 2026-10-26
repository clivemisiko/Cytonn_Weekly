<script setup lang="ts">
import { renderMarkdown } from "@/lib/markdown";

defineProps<{ text: string }>();
</script>

<template>
  <div class="space-y-3" v-html="renderMarkdown(text)" />
</template>
