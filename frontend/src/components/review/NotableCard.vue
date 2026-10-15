<script setup lang="ts">
import { PhCaretDown, PhCaretUp, PhFile, PhWarning } from "@phosphor-icons/vue";
import { computed, ref, useId } from "vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { CHIP } from "@/components/ui/button";
import { friendlyDate } from "@/lib/format";
import { DISMISS_REASONS, KIND_LABELS, checkEdit, figureLine, headlineOf, isEdited, reasonLabel } from "@/lib/notable";
import type { DismissReason, Suggestion } from "@/lib/types";
import WorkingChart from "./WorkingChart.vue";

/**
 * One "Notable this week" suggestion in whichever list it is in: open (Accept, Edit, Dismiss), selected (Edit, Remove from
 * list) or dismissed (Restore). It shows the headline, where its history came from, and, on request, the working: the rule
 * that fired, the window and the points. It only asks its parent to act; nothing here is written into a draft.
 */
const props = defineProps<{ suggestion: Suggestion; mode: "open" | "selected" | "dismissed"; disabled?: boolean }>();
const emit = defineEmits<{
  accept: [];
  edit: [headline: string];
  dismiss: [reason: DismissReason | null];
  restore: [];
}>();

const uid = useId();
const s = computed(() => props.suggestion);
const working = ref(false);
const editing = ref(false);
const dismissing = ref(false);
const draft = ref("");
const reason = ref<DismissReason | "">("");

const editError = computed(() => checkEdit(draft.value));
// A workbook-derived or invented item is marked by shape (the warning glyph) as well as colour.
const caution = computed(() => ["demo", "analyst_workbook"].includes(s.value.provenance.kind));
const figures = computed(() => figureLine(s.value.figures));

function startEdit() {
  draft.value = headlineOf(s.value);
  dismissing.value = false;
  editing.value = true;
}
function saveEdit() {
  if (editError.value) return;
  emit("edit", draft.value);
  editing.value = false;
}
function startDismiss() {
  reason.value = "";
  editing.value = false;
  dismissing.value = true;
}
function confirmDismiss() {
  emit("dismiss", reason.value || null);
  dismissing.value = false;
}
</script>

<template>
  <li class="space-y-2 rounded-md border bg-card px-3 py-3" :aria-labelledby="`${uid}-headline`">
    <div class="flex flex-wrap items-center gap-2">
      <span :class="[CHIP, 'border-input bg-muted text-foreground']">{{ KIND_LABELS[s.kind] }}</span>
      <span :class="[CHIP, caution ? 'border-warn/40 bg-warn/10 text-warn-fg' : 'border-input bg-muted text-foreground']">
        <component :is="caution ? PhWarning : PhFile" weight="bold" class="size-3" aria-hidden="true" />{{ s.provenance.label }}
      </span>
      <span class="font-mono text-xs text-muted-foreground">rank {{ s.rank }}</span>
    </div>

    <p :id="`${uid}-headline`" class="text-sm font-medium [overflow-wrap:anywhere]">{{ headlineOf(s) }}</p>
    <p v-if="isEdited(s)" class="text-xs text-muted-foreground [overflow-wrap:anywhere]">Original: {{ s.headline }}</p>
    <p v-if="figures" class="font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">{{ figures }}</p>
    <p v-if="mode === 'dismissed'" class="text-xs text-muted-foreground">
      {{ s.decision?.dismiss_reason ? `Reason: ${reasonLabel(s.decision.dismiss_reason)}` : "No reason given." }}
    </p>

    <div class="flex flex-wrap items-center gap-2">
      <Button
        variant="ghost"
        size="sm"
        :aria-expanded="working"
        :aria-controls="`${uid}-working`"
        @click="working = !working"
      >
        <component :is="working ? PhCaretUp : PhCaretDown" weight="bold" aria-hidden="true" />{{ working ? "Hide working" : "Show working" }}
      </Button>
      <template v-if="mode === 'open'">
        <Button variant="outline" size="sm" :disabled="disabled" @click="emit('accept')">Accept</Button>
        <Button variant="outline" size="sm" :disabled="disabled" @click="startEdit">Edit</Button>
        <Button variant="outline" size="sm" :disabled="disabled" @click="startDismiss">Dismiss</Button>
      </template>
      <template v-else-if="mode === 'selected'">
        <Button variant="outline" size="sm" :disabled="disabled" @click="startEdit">Edit</Button>
        <Button variant="outline" size="sm" :disabled="disabled" @click="emit('restore')">Remove from list</Button>
      </template>
      <Button v-else variant="outline" size="sm" :disabled="disabled" @click="emit('restore')">Restore</Button>
    </div>

    <div v-if="working" :id="`${uid}-working`" class="space-y-2 rounded-md border bg-muted/50 p-3">
      <dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        <dt class="eyebrow">Rule</dt>
        <dd class="[overflow-wrap:anywhere]">{{ s.working.rule }}</dd>
        <dt class="eyebrow">Series</dt>
        <dd class="[overflow-wrap:anywhere]">{{ s.working.series }}</dd>
        <dt class="eyebrow">Window</dt>
        <dd>{{ s.working.window }}</dd>
      </dl>
      <WorkingChart :working="s.working" />
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-xs">
          <caption class="sr-only">
            Points the rule was applied to
          </caption>
          <thead>
            <tr class="border-b">
              <th scope="col" class="eyebrow py-1 pr-3 text-left">Date</th>
              <th scope="col" class="eyebrow py-1 text-right">Value</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in s.working.points" :key="p.date" class="border-b last:border-b-0">
              <td class="py-1 pr-3 whitespace-nowrap">{{ friendlyDate(p.date) }}</td>
              <td class="py-1 text-right font-mono">{{ p.display }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <form v-if="editing" class="space-y-2" @submit.prevent="saveEdit">
      <label :for="`${uid}-edit`" class="text-xs font-semibold">Reworded headline</label>
      <Textarea
        :id="`${uid}-edit`"
        v-model="draft"
        rows="2"
        :aria-invalid="!!editError || undefined"
        :aria-describedby="editError ? `${uid}-edit-error` : undefined"
        class="py-2"
      />
      <p v-if="editError" :id="`${uid}-edit-error`" class="text-xs font-medium text-flag-fg">{{ editError }}</p>
      <p class="text-xs text-muted-foreground">The original stays as it was and is shown beside yours. Saving selects this item.</p>
      <div class="flex flex-wrap gap-2">
        <Button type="submit" size="sm" :disabled="disabled || !!editError">Save edit</Button>
        <Button variant="ghost" size="sm" @click="editing = false">Cancel</Button>
      </div>
    </form>

    <form v-if="dismissing" class="space-y-2" @submit.prevent="confirmDismiss">
      <label :for="`${uid}-reason`" class="text-xs font-semibold">Reason (optional)</label>
      <select
        :id="`${uid}-reason`"
        v-model="reason"
        class="flex h-10 w-full max-w-xs rounded-md border border-input bg-card px-3 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 md:text-sm"
      >
        <option value="">No reason</option>
        <option v-for="r in DISMISS_REASONS" :key="r.value" :value="r.value">{{ r.label }}</option>
      </select>
      <div class="flex flex-wrap gap-2">
        <Button type="submit" size="sm" :disabled="disabled">Confirm dismissal</Button>
        <Button variant="ghost" size="sm" @click="dismissing = false">Cancel</Button>
      </div>
    </form>
  </li>
</template>
