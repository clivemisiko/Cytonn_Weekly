<script setup lang="ts">
import { PhCloudArrowDown } from "@phosphor-icons/vue";
import { ref } from "vue";
import { RouterLink } from "vue-router";
import Notice from "@/components/review/Notice.vue";
import Button from "@/components/ui/Button.vue";
import { LINK, buttonVariants } from "@/components/ui/button";
import * as api from "@/lib/api";
import { FETCHABLE_ITEMS, type NeedsYou } from "@/lib/chatcards";

const props = defineProps<{ needs: NeedsYou; week: string; formTo: string; section: string }>();
const emit = defineEmits<{ changed: [] }>();

const busy = ref<string | null>(null);
const problem = ref<string | null>(null);
/** The file names last picked per slot: the native "No file chosen" text is hidden, so the name is shown here. */
const picked = ref<Record<string, string>>({});

/** Every button here calls the route the old page's inputs panel calls, and the card is read again after it. */
async function act(key: string, call: () => Promise<unknown>) {
  busy.value = key;
  problem.value = null;
  try {
    await call();
  } catch (err) {
    problem.value = (err as Error).message;
  } finally {
    busy.value = null;
    emit("changed");
  }
}

const fetchBulletin = () => act("fetch", () => api.fetchBulletin(props.week));
const fetchTable = (key: string) => act(`fetch-${key}`, () => api.fetchAnalystTable(props.week, props.section, key));

async function upload(slot: string, event: Event) {
  const input = event.target as HTMLInputElement;
  const files = [...(input.files ?? [])];
  input.value = "";
  if (!files.length) return;
  picked.value = { ...picked.value, [slot]: files.map((f) => f.name).join(", ") };
  await act(`upload-${slot}`, async () => {
    const refused: string[] = [];
    for (const file of files) {
      try {
        await api.uploadInput(props.week, slot, file);
      } catch (err) {
        refused.push(`${file.name}: ${(err as Error).message}`);
      }
    }
    if (refused.length) throw new Error(refused.join("\n"));
  });
}
</script>

<template>
  <section aria-label="Needs you" class="space-y-3 rounded-md border bg-background px-3 py-2.5" data-card="needs_you">
    <h3 class="text-sm font-semibold">Needs you</h3>

    <ul v-if="needs.uploads.length" class="space-y-3">
      <li v-for="u in needs.uploads" :key="u.key" class="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p class="text-sm font-medium">{{ u.label }}</p>
        <p class="text-xs text-muted-foreground">{{ u.why }}</p>
        <div class="flex flex-wrap items-center gap-2 sm:ml-auto">
          <Button v-if="u.fetchable" variant="outline" size="sm" class="min-h-11" :disabled="busy !== null" @click="fetchBulletin">
            <PhCloudArrowDown weight="bold" data-icon="inline-start" aria-hidden="true" />
            {{ busy === "fetch" ? "Fetching…" : "Fetch from CBK" }}<span class="sr-only">: {{ u.label }}</span>
          </Button>
          <!-- The same input, visually hidden: the label is the button, and it shows the ring while the input has keyboard focus. -->
          <label :class="[buttonVariants({ variant: 'outline', size: 'sm' }), 'min-h-11 cursor-pointer has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50']">
            <input type="file" multiple accept=".pdf,.xlsx" :disabled="busy !== null" :aria-label="`Upload ${u.label}`" class="sr-only" @change="upload(u.key, $event)" />
            <span aria-hidden="true">Choose file</span>
          </label>
        </div>
        <p v-if="picked[u.key]" class="w-full text-xs [overflow-wrap:anywhere]">Chosen: {{ picked[u.key] }}</p>
      </li>
    </ul>

    <ul v-if="needs.fetch.length" class="space-y-3">
      <li v-for="e in needs.fetch" :key="e.key" class="space-y-1.5">
        <p class="text-sm font-medium">{{ e.label }}</p>
        <p class="text-xs text-muted-foreground">{{ e.why }}</p>
        <Button variant="outline" size="sm" :disabled="busy !== null" @click="fetchTable(e.key)">
          <PhCloudArrowDown weight="bold" data-icon="inline-start" aria-hidden="true" />
          {{ busy === `fetch-${e.key}` ? "Fetching…" : FETCHABLE_ITEMS[e.key] }}<span class="sr-only">: {{ e.label }}</span>
        </Button>
      </li>
    </ul>

    <div v-if="needs.typed.length" class="space-y-1">
      <p class="text-sm font-medium">Typed on the inputs form</p>
      <ul class="list-disc space-y-0.5 pl-5 text-sm [overflow-wrap:anywhere]">
        <li v-for="e in needs.typed" :key="e.key">{{ e.label }}: {{ e.why }}</li>
      </ul>
    </div>
    <div v-if="needs.confirm.length" class="space-y-1">
      <p class="text-sm font-medium">To confirm on the inputs form</p>
      <ul class="list-disc space-y-0.5 pl-5 text-sm [overflow-wrap:anywhere]">
        <li v-for="e in needs.confirm" :key="e.key">{{ e.label }}: {{ e.why }}</li>
      </ul>
    </div>
    <RouterLink v-if="needs.typed.length || needs.confirm.length" :to="formTo" :class="['inline-block text-sm', LINK]">Open inputs form</RouterLink>

    <Notice v-if="problem" role="alert" class="font-medium whitespace-pre-line">{{ problem }}</Notice>
  </section>
</template>
