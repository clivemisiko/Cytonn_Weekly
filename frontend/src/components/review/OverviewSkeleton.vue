<script setup lang="ts">
const SECTIONS = [
  "Company Updates",
  "Fixed Income",
  "Equities",
  "Real Estate",
  "Digital Payments",
  "Focus of the Week",
];
const STAGES = ["Inputs & Data", "AI Research & Draft", "Review & Verify", "Word Export"];
const TALLIES = ["Approved", "In review", "Not drafted", "Rejected", "Not available"];
</script>

<template>
  <div aria-busy="true" aria-label="Loading report dashboard" class="min-h-screen">
    <!-- Header / Masthead Skeleton -->
    <header class="border-b bg-card">
      <div class="w-full px-4 py-5 sm:px-6 space-y-2">
        <div class="flex items-center gap-2">
          <span class="size-2 rounded-full bg-primary/40 animate-pulse" aria-hidden="true" />
          <div class="h-3 w-24 rounded-md bg-border/60 animate-pulse" />
        </div>
        <div class="flex flex-wrap items-end justify-between gap-4">
          <div class="h-8 w-56 rounded-md bg-border/70 animate-pulse" />
          <div class="h-4 w-32 rounded-md bg-border/40 animate-pulse" />
        </div>
        <div class="h-4 w-80 max-w-full rounded-md bg-border/40 animate-pulse" />
      </div>
    </header>

    <!-- Main Workspace Grid: mirrors PageGrid layout -->
    <div class="grid w-full gap-4 px-3 pt-4 pb-16 sm:px-5 lg:gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_clamp(20rem,25vw,28rem)]">
      <!-- Main Content Column -->
      <div class="@container w-full min-w-0 space-y-5">
        <!-- ReportPicker Skeleton Card -->
        <div class="rounded-xl border border-border bg-card p-4 space-y-3 shadow-xs">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="h-4 w-36 rounded-md bg-border/60 animate-pulse" />
            <div class="h-4 w-28 rounded-md bg-border/40 animate-pulse" />
          </div>
          <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
            <div class="h-10 rounded-md border border-input bg-muted/40 animate-pulse" />
            <div class="h-10 rounded-md border border-input bg-muted/40 animate-pulse" />
            <div class="h-10 rounded-md bg-border/60 animate-pulse" />
          </div>
        </div>

        <!-- Publication Pipeline Stepper Skeleton Card -->
        <div class="rounded-xl border border-border bg-card p-4.5 space-y-3 shadow-xs">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <div class="h-3.5 w-32 rounded bg-border/60 animate-pulse" />
              <div class="h-5 w-24 rounded-full bg-primary/15 animate-pulse" />
            </div>
            <div class="h-3.5 w-28 rounded bg-border/40 animate-pulse" />
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div
              v-for="(stage, i) in STAGES"
              :key="stage"
              class="flex items-center gap-2 rounded-lg border border-border/80 bg-muted/40 p-2.5"
            >
              <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted-foreground/30 font-mono text-[10px] font-bold text-foreground">
                {{ i + 1 }}
              </span>
              <span class="truncate font-medium text-muted-foreground/70">{{ stage }}</span>
            </div>
          </div>
        </div>

        <!-- Section List Heading Skeleton -->
        <div class="flex items-center justify-between gap-4 pt-1">
          <div class="flex items-center gap-2">
            <div class="size-4 rounded bg-border/60 animate-pulse" />
            <div class="h-5 w-48 rounded bg-border/70 animate-pulse" />
          </div>
        </div>

        <!-- Section Rows Skeletons: 6 Realistic Cards -->
        <ol class="space-y-4">
          <li
            v-for="(name, index) in SECTIONS"
            :key="name"
            class="@container"
          >
            <div class="grid grid-cols-1 gap-x-3.5 @md:grid-cols-[2.5rem_minmax(0,1fr)]">
              <!-- Index Circle -->
              <span class="hidden size-10 place-items-center rounded-full border border-border/80 bg-muted/60 font-mono text-xs font-semibold text-foreground/70 shadow-xs @md:grid" aria-hidden="true">
                {{ index + 1 }}
              </span>

              <!-- Card -->
              <div class="min-w-0 space-y-3.5 rounded-xl border border-border bg-card p-4.5 shadow-xs @lg:p-6 border-l-4 border-l-border/60">
                <div class="flex items-start justify-between gap-4">
                  <div class="min-w-0 space-y-2.5">
                    <div class="flex items-center gap-2.5">
                      <h3 class="text-lg font-semibold tracking-tight text-foreground/80">{{ name }}</h3>
                    </div>
                    <div class="flex flex-wrap items-center gap-2">
                      <span class="h-6 w-20 rounded-md bg-border/50 animate-pulse" />
                      <span class="h-4 w-32 rounded bg-border/30 animate-pulse" />
                    </div>
                  </div>

                  <!-- Progress Ring Silhouette -->
                  <div class="relative hidden size-12 shrink-0 rounded-full border-[3.5px] border-border/50 animate-pulse @md:grid place-items-center" aria-hidden="true">
                    <span class="size-2 rounded-full bg-border/60" />
                  </div>
                </div>

                <!-- Summary Line -->
                <div class="h-4 w-48 rounded bg-border/40 animate-pulse" />

                <!-- Action Button Row -->
                <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t pt-3">
                  <div class="h-4 w-24 rounded bg-border/30 animate-pulse" />
                  <div class="flex gap-2 ml-auto">
                    <div class="h-9 w-28 rounded-md bg-border/60 animate-pulse" />
                    <div class="h-9 w-24 rounded-md bg-border/40 animate-pulse" />
                  </div>
                </div>
              </div>
            </div>
          </li>
        </ol>
      </div>

      <!-- Right Aside Column ("Report status") -->
      <aside aria-label="Report status skeleton" class="min-w-0 min-[1100px]:self-start min-[1100px]:border-l min-[1100px]:pl-4 space-y-5">
        <div class="flex items-center justify-between gap-2 pb-2">
          <div class="h-4 w-28 rounded bg-border/60 animate-pulse" />
        </div>

        <!-- Tally Scorecard Grid Skeleton -->
        <dl role="group" aria-label="Scorecard" class="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border shadow-xs @xl:grid-cols-5">
          <div v-for="label in TALLIES" :key="label" class="flex flex-col gap-1.5 bg-card px-4 py-3.5 last:col-span-2 @xl:last:col-span-1">
            <dt class="eyebrow text-[11px] text-muted-foreground/70">{{ label }}</dt>
            <dd class="h-6 w-12 rounded bg-border/50 animate-pulse" />
          </div>
        </dl>

        <!-- Export Bar Skeleton Card -->
        <section class="space-y-3.5 rounded-xl border border-border bg-card p-4.5 shadow-xs">
          <div class="space-y-1.5">
            <div class="h-4.5 w-36 rounded bg-border/70 animate-pulse" />
            <div class="h-3.5 w-full rounded bg-border/40 animate-pulse" />
            <div class="h-3.5 w-2/3 rounded bg-border/30 animate-pulse" />
          </div>
          <div class="h-10 w-full rounded-md bg-border/60 animate-pulse" />
          <div class="flex flex-wrap gap-1.5 pt-1">
            <div v-for="i in 6" :key="i" class="h-5 w-24 rounded-full bg-border/35 animate-pulse" />
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

