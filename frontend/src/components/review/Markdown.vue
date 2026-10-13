<script setup lang="ts">
import { renderMarkdown } from "@/lib/markdown";

/** Drafted markdown, rendered safely (lib/markdown.ts): no raw HTML, only safe links. */
defineProps<{ text: string }>();
</script>

<template>
  <div class="space-y-3" v-html="renderMarkdown(text)" />
</template>
