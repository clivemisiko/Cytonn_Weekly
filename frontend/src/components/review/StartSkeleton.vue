<script setup lang="ts">
const CHECKLIST = ["AI Engine", "Focus Topic", "Section Text", "Analyst Form", "Draft Slot"];
</script>

<template>
  <div aria-busy="true" aria-label="Loading section start screen" class="min-h-screen">
    <!-- Masthead Skeleton -->
    <header class="border-b bg-card">
      <div class="w-full px-4 py-5 sm:px-6 space-y-2">
        <div class="flex items-center gap-2">
          <span class="size-2 rounded-full bg-primary/40 animate-pulse" aria-hidden="true" />
          <div class="h-3 w-28 rounded-md bg-border/60 animate-pulse" />
        </div>
        <div class="flex flex-wrap items-end justify-between gap-4">
          <div class="h-8 w-64 rounded-md bg-border/70 animate-pulse" />
          <div class="h-4 w-36 rounded-md bg-border/40 animate-pulse" />
        </div>
        <div class="h-4 w-80 max-w-full rounded-md bg-border/40 animate-pulse" />
      </div>
    </header>

    <!-- Main Workspace Grid: PageGrid format -->
    <div class="grid w-full gap-4 px-3 pt-4 pb-16 sm:px-5 lg:gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_clamp(20rem,25vw,28rem)]">
      <!-- Main Content Column -->
      <div class="@container w-full min-w-0 space-y-6">
        <!-- Pre-flight Readiness Checklist Skeleton -->
        <div class="rounded-xl border border-border bg-card p-4.5 shadow-xs space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="size-2 rounded-full bg-ok animate-pulse" />
              <div class="h-4 w-36 rounded bg-border/70 animate-pulse" />
            </div>
            <div class="h-4 w-28 rounded bg-border/40 animate-pulse" />
          </div>
          <div class="flex flex-wrap gap-2 pt-1">
            <div
              v-for="item in CHECKLIST"
              :key="item"
              class="flex items-center gap-1.5 rounded-full border border-border/80 bg-muted/40 px-3 py-1 text-xs"
            >
              <div class="size-2 rounded-full bg-border/70 animate-pulse" />
              <span class="font-medium text-muted-foreground/70">{{ item }}</span>
            </div>
          </div>
        </div>

        <!-- Section Input Configuration Card Skeleton -->
        <div class="rounded-xl border border-border bg-card p-6 shadow-xs space-y-5">
          <div class="space-y-2 border-b pb-4">
            <div class="h-5 w-48 rounded bg-border/70 animate-pulse" />
            <div class="h-3.5 w-72 rounded bg-border/40 animate-pulse" />
          </div>

          <!-- Input Fields / Form Skeleton -->
          <div class="space-y-4">
            <div class="space-y-2">
              <div class="h-4 w-28 rounded bg-border/60 animate-pulse" />
              <div class="h-10 w-full rounded-lg border border-input bg-muted/30 animate-pulse" />
            </div>
            <div class="space-y-2">
              <div class="h-4 w-32 rounded bg-border/60 animate-pulse" />
              <div class="h-28 w-full rounded-lg border border-input bg-muted/30 animate-pulse" />
            </div>
          </div>

          <!-- Action Button Skeleton -->
          <div class="flex items-center justify-between pt-2">
            <div class="h-4 w-40 rounded bg-border/40 animate-pulse" />
            <div class="h-11 w-36 rounded-lg bg-primary/30 animate-pulse" />
          </div>
        </div>
      </div>

      <!-- Right Column: Section Metadata & History Aside -->
      <aside class="space-y-4">
        <div class="rounded-xl border border-border bg-card p-4.5 shadow-xs space-y-4">
          <div class="border-b pb-3">
            <div class="h-5 w-32 rounded bg-border/70 animate-pulse" />
          </div>
          <dl class="space-y-3">
            <div>
              <div class="h-3 w-16 rounded bg-border/50 animate-pulse mb-1" />
              <div class="h-4 w-28 rounded bg-border/70 animate-pulse" />
            </div>
            <div>
              <div class="h-3 w-20 rounded bg-border/50 animate-pulse mb-1" />
              <div class="h-4 w-40 rounded bg-border/70 animate-pulse" />
            </div>
            <div>
              <div class="h-3 w-24 rounded bg-border/50 animate-pulse mb-1" />
              <div class="h-4 w-32 rounded bg-border/70 animate-pulse" />
            </div>
          </dl>
        </div>
      </aside>
    </div>
  </div>
</template>

