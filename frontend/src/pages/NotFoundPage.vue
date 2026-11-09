<script setup lang="ts">
import { RouterLink } from "vue-router";
import PageGrid from "@/components/nav/PageGrid.vue";
import Masthead from "@/components/review/Masthead.vue";
import { buttonVariants } from "@/components/ui/button";
import { shell } from "@/lib/shell";

shell.invalidate(); // the rail knows no section's state here
</script>

<template>
  <main id="main" tabindex="-1">
    <Masthead wide title="Page not found" />
    <PageGrid>
      <div class="space-y-4 rounded-lg border bg-card p-6">
        <p class="text-sm text-muted-foreground">We couldn't find the page you're looking for. Please check the web address or return to the overview to continue.</p>
        <div>
          <RouterLink to="/overview" :class="buttonVariants({ variant: 'default' })">
            Return to overview
          </RouterLink>
        </div>
      </div>
    </PageGrid>
  </main>
</template>
