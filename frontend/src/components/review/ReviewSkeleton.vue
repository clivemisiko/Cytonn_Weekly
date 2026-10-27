<script setup lang="ts">
const TILES = [
  { label: "Clean items", count: "—", tone: "border-ok/30 bg-ok/5 text-ok" },
  { label: "Flagged items", count: "—", tone: "border-flag/30 bg-flag/5 text-flag" },
  { label: "Fix needed", count: "—", tone: "border-warn/30 bg-warn/5 text-warn" },
];

const SKELETON_ITEMS = [
  { tone: "border-l-flag", badge: "FLAGGED", w: "w-4/5" },
  { tone: "border-l-warn", badge: "FIX NEEDED", w: "w-3/4" },
  { tone: "border-l-ok", badge: "OK", w: "w-5/6" },
];
</script>

<template>
  <div aria-busy="true" aria-label="Loading section review" class="min-h-screen">
    <!-- Masthead Skeleton -->
    <header class="border-b bg-card">
      <div class="w-full px-4 py-5 sm:px-6 space-y-2">
        <div class="flex items-center gap-2">
          <span class="size-2 rounded-full bg-primary/40 animate-pulse" aria-hidden="true" />
          <div class="h-3 w-28 rounded-md bg-border/60 animate-pulse" />
        </div>
        <div class="flex flex-wrap items-end justify-between gap-4">
          <div class="h-8 w-72 rounded-md bg-border/70 animate-pulse" />
          <div class="h-4 w-40 rounded-md bg-border/40 animate-pulse" />
        </div>
        <div class="h-4 w-96 max-w-full rounded-md bg-border/40 animate-pulse" />
      </div>
    </header>

    <!-- Sticky Status Bar Skeleton -->
    <div class="sticky top-(--topbar-h) z-30 border-b border-border bg-card/95 px-4 py-3 shadow-xs backdrop-blur-sm sm:px-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <div class="h-8 w-24 rounded-lg bg-muted/60 animate-pulse" />
          <div class="h-5 w-32 rounded-full bg-border/60 animate-pulse" />
        </div>
        <div class="flex items-center gap-2">
          <div class="h-9 w-28 rounded-lg bg-border/50 animate-pulse" />
          <div class="h-9 w-32 rounded-lg bg-primary/25 animate-pulse" />
        </div>
      </div>
    </div>

    <!-- Main Workspace Grid: wide-body PageGrid format -->
    <div class="grid w-full gap-4 px-3 pt-4 pb-16 sm:px-5 lg:gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_clamp(20rem,25vw,28rem)]">
      <!-- Left Column: Draft Content & Scorecards -->
      <div class="@container w-full min-w-0 space-y-6">
        <!-- 3 Count Tiles Skeleton -->
        <div class="grid grid-cols-1 gap-3 @min-[34rem]:grid-cols-3">
          <div
            v-for="tile in TILES"
            :key="tile.label"
            class="rounded-xl border p-4 shadow-xs space-y-2"
            :class="tile.tone"
          >
            <div class="flex items-center justify-between">
              <span class="text-xs font-semibold uppercase tracking-wider opacity-80">{{ tile.label }}</span>
              <div class="size-4 rounded-full bg-current opacity-20 animate-pulse" />
            </div>
            <div class="h-7 w-12 rounded bg-current opacity-20 animate-pulse" />
            <div class="h-3 w-24 rounded bg-current opacity-20 animate-pulse" />
          </div>
        </div>

        <!-- Draft Paper Container Skeleton -->
        <div class="rounded-xl border border-border bg-card p-6 shadow-xs sm:p-8 space-y-6">
          <div class="flex items-center justify-between border-b pb-4">
            <div class="space-y-2">
              <div class="h-6 w-64 rounded bg-border/70 animate-pulse" />
              <div class="h-3.5 w-40 rounded bg-border/40 animate-pulse" />
            </div>
            <div class="h-7 w-20 rounded-md bg-muted/60 animate-pulse" />
          </div>

          <!-- Paragraph 1 -->
          <div class="space-y-2.5">
            <div class="h-4 w-full rounded bg-border/50 animate-pulse" />
            <div class="h-4 w-[96%] rounded bg-border/50 animate-pulse" />
            <div class="h-4 w-[92%] rounded bg-border/50 animate-pulse" />
            <div class="h-4 w-4/5 rounded bg-border/40 animate-pulse" />
          </div>

          <!-- Structured Data Table Silhouette -->
          <div class="rounded-lg border border-border/80 p-4 space-y-3 bg-muted/20">
            <div class="flex items-center justify-between">
              <div class="h-4 w-48 rounded bg-border/60 animate-pulse" />
              <div class="h-4 w-16 rounded bg-border/40 animate-pulse" />
            </div>
            <div class="space-y-2">
              <div class="h-8 rounded bg-muted/60 animate-pulse" />
              <div class="h-7 rounded bg-muted/40 animate-pulse" />
              <div class="h-7 rounded bg-muted/40 animate-pulse" />
              <div class="h-7 rounded bg-muted/40 animate-pulse" />
            </div>
          </div>

          <!-- Paragraph 2 -->
          <div class="space-y-2.5">
            <div class="h-4 w-full rounded bg-border/50 animate-pulse" />
            <div class="h-4 w-[94%] rounded bg-border/50 animate-pulse" />
            <div class="h-4 w-3/4 rounded bg-border/40 animate-pulse" />
          </div>
        </div>

        <!-- Notable Suggestions Panel Skeleton -->
        <div class="rounded-xl border border-border bg-card p-6 shadow-xs space-y-4">
          <div class="flex items-center justify-between border-b pb-3">
            <div class="space-y-1">
              <div class="h-5 w-40 rounded bg-border/70 animate-pulse" />
              <div class="h-3 w-64 rounded bg-border/40 animate-pulse" />
            </div>
            <div class="h-6 w-24 rounded-full bg-border/40 animate-pulse" />
          </div>
          <div class="space-y-3">
            <div class="h-16 rounded-lg border border-border/60 bg-muted/30 p-3 animate-pulse" />
            <div class="h-16 rounded-lg border border-border/60 bg-muted/30 p-3 animate-pulse" />
          </div>
        </div>
      </div>

      <!-- Right Column: Review Items Pane Skeleton -->
      <aside class="space-y-4">
        <div class="rounded-xl border border-border bg-card p-4.5 shadow-xs space-y-4">
          <!-- Items Pane Header -->
          <div class="flex items-center justify-between border-b pb-3">
            <div class="space-y-1">
              <div class="h-5 w-28 rounded bg-border/70 animate-pulse" />
              <div class="h-3 w-36 rounded bg-border/40 animate-pulse" />
            </div>
            <div class="h-6 w-16 rounded-full bg-primary/20 animate-pulse" />
          </div>

          <!-- Filter Tabs Skeleton -->
          <div class="grid grid-cols-4 gap-1.5 rounded-lg bg-muted/50 p-1">
            <div class="h-7 rounded bg-background shadow-xs animate-pulse" />
            <div class="h-7 rounded bg-transparent animate-pulse" />
            <div class="h-7 rounded bg-transparent animate-pulse" />
            <div class="h-7 rounded bg-transparent animate-pulse" />
          </div>

          <!-- Quick Action Banner Placeholder -->
          <div class="h-10 rounded-lg border border-ok/30 bg-ok/10 animate-pulse" />

          <!-- Realistic Review Item Card Silhouettes -->
          <div class="space-y-3">
            <div
              v-for="(item, i) in SKELETON_ITEMS"
              :key="i"
              class="rounded-lg border border-border/80 bg-muted/20 p-3.5 space-y-2.5 border-l-4"
              :class="item.tone"
            >
              <div class="flex items-center justify-between">
                <span class="rounded px-1.5 py-0.5 font-mono text-[10px] font-bold tracking-wider bg-muted text-muted-foreground">
                  {{ item.badge }}
                </span>
                <div class="h-3 w-16 rounded bg-border/50 animate-pulse" />
              </div>
              <div class="space-y-1.5">
                <div class="h-3.5 rounded bg-border/60 animate-pulse" :class="item.w" />
                <div class="h-3 rounded bg-border/40 animate-pulse w-1/2" />
              </div>
              <div class="flex items-center justify-end gap-2 pt-1 border-t border-border/40">
                <div class="h-6 w-16 rounded bg-border/40 animate-pulse" />
                <div class="h-6 w-16 rounded bg-border/60 animate-pulse" />
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

