<script setup lang="ts">
import { PhCircleNotch, PhTrash, PhUploadSimple } from "@phosphor-icons/vue";
import { computed, onMounted, onUnmounted, ref, shallowRef, useTemplateRef } from "vue";
import Notice from "@/components/review/Notice.vue";
import RedraftDialog from "@/components/review/RedraftDialog.vue";
import Button from "@/components/ui/Button.vue";
import UploadProgress from "@/components/ui/UploadProgress.vue";
import { FIELD, LINK } from "@/components/ui/button";
import * as api from "@/lib/api";
import { countsLine, currencyWord, listText, parseFundSnip, parseList, whyNotYet, withFix, type Fix, type FundRow, type FundSnip } from "@/lib/fundsnip";

const props = defineProps<{ week: string; section: string }>();
const emit = defineEmits<{ changed: [] }>();

const snip = shallowRef<FundSnip | null>(null);
const busy = ref<string | null>(null);
const problem = ref<string | null>(null);
const kept = ref<string | null>(null);
const published = ref("");
const listDraft = ref("");
const typedRates = ref<Record<string, string>>({});
const picker = useTemplateRef<HTMLInputElement>("picker");
let generation = 0;

function take(data: unknown) {
  const next = parseFundSnip(data);
  if (!next) throw new Error("The fund page came back in a shape this page does not know.");
  snip.value = next;
  listDraft.value = listText(next.include);
}

async function load() {
  const mine = ++generation;
  try {
    const data = await api.getFundSnip(props.week);
    if (mine === generation) take(data);
  } catch (err) {
    if (mine === generation) problem.value = (err as Error).message;
  }
}
onMounted(load);
onUnmounted(() => generation++);

/** Every button calls one route; the card then shows what the server answered, never what it expects. */
async function act(key: string, call: () => Promise<unknown>, after?: (answer: unknown) => void | Promise<void>) {
  busy.value = key;
  problem.value = null;
  kept.value = null;
  try {
    const answer = await call();
    if (after) await after(answer);
    else take(answer);
  } catch (err) {
    problem.value = (err as Error).message;
  } finally {
    busy.value = null;
  }
}

const uploadingName = ref<string | null>(null);
function picked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  uploadingName.value = file.name;
  // act never throws: a refusal lands in `problem` and the card shows what the server still holds
  void act("upload", () => api.uploadFundSnip(props.week, file)).then(() => (uploadingName.value = null));
}

const read = () => act("read", () => api.readFundSnip(props.week));
// The page image only: a table already kept on the form stays there (DELETE .../fund-snip).
const askingRemove = ref(false);
const removeImage = () => {
  askingRemove.value = false;
  return act("remove", () => api.deleteFundSnip(props.week));
};
const edits = (fixes: Record<string, Fix>, typed = snip.value?.typed ?? []) => api.saveFundSnipEdits(props.week, { fixes, typed });
const fix = (id: number, patch: Fix) => act(`fix-${id}`, () => edits(withFix(snip.value?.fixes ?? {}, id, patch)));
const decide = (row: { name: string }, decision: "include" | "exclude" | "alias", to?: string) =>
  act(`decide-${row.name}`, async () => {
    await api.decideFund(row.name, decision, to);
    return api.getFundSnip(props.week);
  });
const addTyped = (fund: string) =>
  act(`typed-${fund}`, async () => {
    const typed = [...(snip.value?.typed ?? []), { fund, rate: typedRates.value[fund] ?? "" }];
    await edits(snip.value?.fixes ?? {}, typed);
    typedRates.value = { ...typedRates.value, [fund]: "" };
    return api.getFundSnip(props.week);
  });
const removeTyped = (fund: string) => act(`typed-${fund}`, () => edits(snip.value?.fixes ?? {}, (snip.value?.typed ?? []).filter((t) => t.fund !== fund)));
const saveList = () =>
  act("list", async () => {
    await api.saveFundList(parseList(listDraft.value));
    return api.getFundSnip(props.week);
  });
const confirm = () =>
  act("confirm", () => api.confirmFundSnip(props.week, props.section, published.value), async () => {
    const rows = (snip.value?.kept ?? 0) + (snip.value?.typed.length ?? 0);
    kept.value = `The table of ${rows} funds is kept on the form. Its ranks are worked out here, equal rates sharing a rank.`;
    emit("changed");
    take(await api.getFundSnip(props.week));
  });

const why = computed(() => (snip.value ? whyNotYet(snip.value, published.value) : []));
const status = (r: FundRow) => (r.duplicate ? "Same list fund as another row" : r.unresolved.length ? "Cell not read: type it or ignore the row" : r.group === "new" ? "Not on the list: decide" : "On the list");
const megabytes = (bytes: number) => `${(bytes / 1_048_576).toFixed(1)} MB`;
</script>

<template>
  <section aria-label="Money market fund table" class="space-y-3 rounded-md border bg-background px-3 py-2.5" data-card="fund_snip">
    <h3 class="text-sm font-semibold">Money market fund table from the Daily Nation page</h3>
    <p class="text-xs text-muted-foreground">
      Upload the Unit Trusts page. The tool reads each cell twice and keeps one only when both readings agree. Nothing reaches the form until you press Use this table.
    </p>

    <div class="flex flex-wrap items-center gap-2">
      <input ref="picker" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" class="sr-only" tabindex="-1" aria-hidden="true" @change="picked" />
      <Button variant="outline" size="sm" :disabled="busy !== null" @click="picker?.click()">
        <PhUploadSimple weight="bold" data-icon="inline-start" aria-hidden="true" />
        {{ busy === "upload" ? "Uploading…" : snip?.image ? "Replace the page image" : "Choose the page image" }}
      </Button>
      <Button v-if="snip?.image" variant="outline" size="sm" :disabled="busy !== null" @click="read">
        <PhCircleNotch v-if="busy === 'read'" weight="bold" data-icon="inline-start" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {{ busy === "read" ? "Reading the page, about a minute…" : snip.read ? "Read the page again" : "Read the page" }}
      </Button>
      <button v-if="snip?.image" type="button" :disabled="busy !== null" :class="['inline-flex items-center gap-1 text-xs disabled:opacity-50', LINK]" @click="askingRemove = true">
        <PhTrash weight="bold" class="size-3" aria-hidden="true" />
        Remove the image
      </button>
    </div>
    <UploadProgress v-if="busy === 'upload'" :name="uploadingName ?? 'the page image'" />
    <RedraftDialog
      :open="askingRemove"
      :title="snip?.image ? `Remove the Daily Nation page image (${snip.image.type === 'jpeg' ? 'JPEG' : 'PNG'}, ${megabytes(snip.image.size)})?` : 'Remove the Daily Nation page image?'"
      :notes="['The page image and its reading are taken out of this week’s inputs. A fund table already kept on the form stays there.', 'Saved drafts, approved reviews and the history store are not changed.']"
      confirm-label="Remove the image"
      @confirm="removeImage"
      @cancel="askingRemove = false"
    />
    <div v-if="snip?.image" class="flex flex-wrap items-end gap-3">
      <img :src="api.fundSnipImageUrl(week, snip.image.sha256)" alt="The Daily Nation page uploaded for this week" class="h-16 w-auto max-w-40 rounded-sm border bg-white object-contain" />
      <p class="font-mono text-xs text-muted-foreground">{{ snip.image.type === "jpeg" ? "JPEG" : "PNG" }}, {{ megabytes(snip.image.size) }}</p>
    </div>

    <template v-if="snip?.read">
      <p class="text-sm" data-testid="fund-counts">{{ countsLine(snip) }}</p>

      <div v-if="snip.rows.length" role="region" tabindex="0" aria-label="Fund rows read from the page" class="overflow-x-auto rounded-md border">
        <table class="w-full min-w-[34rem] text-left text-sm">
          <caption class="sr-only">Fund rows read from the page, with the funds still to decide</caption>
          <thead class="text-xs text-muted-foreground">
            <tr>
              <th scope="col" class="px-2 py-1.5 font-semibold">Fund on the page</th>
              <th scope="col" class="px-2 py-1.5 font-semibold">Currency</th>
              <th scope="col" class="px-2 py-1.5 font-semibold">Annual rate (%)</th>
              <th scope="col" class="px-2 py-1.5 font-semibold">Status and action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in snip.rows" :key="r.id" class="border-t align-top">
              <td class="px-2 py-1.5 [overflow-wrap:anywhere]">
                <input v-if="r.unresolved.includes('name')" :aria-label="`Fund name, row ${r.id + 1}`" :value="r.name" :class="[FIELD, 'h-8 w-full text-sm']" @change="fix(r.id, { name: ($event.target as HTMLInputElement).value })" />
                <template v-else>
                  {{ r.name }}
                  <span v-if="r.listName && r.listName !== r.name" class="block text-xs text-muted-foreground">Listed as {{ r.listName }}</span>
                </template>
              </td>
              <td class="px-2 py-1.5">
                <select v-if="r.unresolved.includes('currency')" :aria-label="`Currency, row ${r.id + 1}`" :class="[FIELD, 'h-8 text-sm']" :value="r.currency" @change="fix(r.id, { currency: ($event.target as HTMLSelectElement).value as 'KES' | 'USD' })">
                  <option value="">Not read</option>
                  <option value="KES">Kenya Shilling</option>
                  <option value="USD">USD</option>
                </select>
                <template v-else>{{ currencyWord(r.currency) }}</template>
              </td>
              <td class="px-2 py-1.5">
                <input v-if="r.unresolved.includes('rate')" inputmode="decimal" :aria-label="`Annual rate, row ${r.id + 1}`" :value="r.rate ?? ''" :class="[FIELD, 'h-8 w-24 text-sm']" @change="fix(r.id, { rate: ($event.target as HTMLInputElement).value.trim() })" />
                <template v-else>{{ r.rate }}</template>
              </td>
              <td class="space-y-1 px-2 py-1.5">
                <p class="text-xs">{{ status(r) }}</p>
                <div class="flex flex-wrap items-center gap-1.5">
                  <template v-if="r.group === 'new' && !r.unresolved.length">
                    <Button variant="outline" size="xs" :disabled="busy !== null" @click="decide(r, 'include')">Put on the list<span class="sr-only">: {{ r.name }}</span></Button>
                    <Button variant="outline" size="xs" :disabled="busy !== null" @click="decide(r, 'exclude')">Leave out<span class="sr-only">: {{ r.name }}</span></Button>
                    <select :aria-label="`Same fund as, for ${r.name}`" :class="[FIELD, 'h-6 max-w-44 px-1 text-xs']" :disabled="busy !== null" @change="(e) => { const to = (e.target as HTMLSelectElement).value; if (to) void decide(r, 'alias', to); }">
                      <option value="">Same fund as…</option>
                      <option v-for="n in snip.include" :key="n" :value="n">{{ n }}</option>
                    </select>
                  </template>
                  <Button variant="ghost" size="xs" :disabled="busy !== null" @click="fix(r.id, { ignore: true })">Ignore the row<span class="sr-only">: {{ r.name || `row ${r.id + 1}` }}</span></Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <details v-if="snip.leftOut.length || snip.ignored.length" class="rounded-md border px-2 py-1.5 text-sm">
        <summary class="cursor-pointer text-sm font-medium">Left out ({{ snip.leftOut.length + snip.ignored.length }})</summary>
        <ul class="mt-1.5 space-y-1">
          <li v-for="l in snip.leftOut" :key="`l-${l.id}`" class="flex flex-wrap items-center justify-between gap-2 [overflow-wrap:anywhere]">
            <span>{{ l.name }} <span class="text-xs text-muted-foreground">(left out {{ l.why }})</span></span>
            <Button variant="outline" size="xs" :disabled="busy !== null" @click="decide(l, 'include')">Put on the list<span class="sr-only">: {{ l.name }}</span></Button>
          </li>
          <li v-for="i in snip.ignored" :key="`i-${i.id}`" class="flex flex-wrap items-center justify-between gap-2 [overflow-wrap:anywhere]">
            <span>{{ i.name || `Row ${i.id + 1}` }} <span class="text-xs text-muted-foreground">(row ignored)</span></span>
            <Button variant="outline" size="xs" :disabled="busy !== null" @click="fix(i.id, { ignore: false })">Use the row again<span class="sr-only">: {{ i.name }}</span></Button>
          </li>
        </ul>
      </details>

      <div class="space-y-1.5">
        <p class="text-sm font-medium">Funds on the list that the page does not carry ({{ snip.notOnPage.length + snip.typed.length }})</p>
        <p class="text-xs text-muted-foreground">Type a rate for one to keep it in the table. It ranks with the others and is saved as typed.</p>
        <ul class="space-y-1.5">
          <li v-for="t in snip.typed" :key="`t-${t.fund}`" class="flex flex-wrap items-center justify-between gap-2 text-sm [overflow-wrap:anywhere]">
            <span>{{ t.fund }}: {{ t.rate }}% <span class="text-xs text-muted-foreground">(typed)</span></span>
            <Button variant="outline" size="xs" :disabled="busy !== null" @click="removeTyped(t.fund)">Remove<span class="sr-only">: {{ t.fund }}</span></Button>
          </li>
          <li v-for="n in snip.notOnPage" :key="`n-${n}`" class="flex flex-wrap items-center gap-2 text-sm">
            <span class="min-w-0 [overflow-wrap:anywhere]">{{ n }}</span>
            <input v-model="typedRates[n]" inputmode="decimal" :aria-label="`Annual rate for ${n}`" placeholder="Rate (%)" :class="[FIELD, 'h-8 w-24 text-sm']" />
            <Button variant="outline" size="xs" :disabled="busy !== null || !(typedRates[n] ?? '').trim()" @click="addTyped(n)">Add<span class="sr-only">: {{ n }}</span></Button>
          </li>
        </ul>
      </div>

      <div class="space-y-1.5">
        <label for="fund-snip-published" class="text-sm font-medium">Fund table published on</label>
        <input id="fund-snip-published" v-model="published" type="date" :class="[FIELD, 'h-8 w-44 text-sm']" />
        <p class="text-xs text-muted-foreground">The day of the Daily Nation paper, a day of the report's week.</p>
        <ul v-if="why.length" id="fund-snip-why" class="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
          <li v-for="w in why" :key="w">{{ w }}</li>
        </ul>
        <Button :disabled="busy !== null || why.length > 0" :aria-describedby="why.length ? 'fund-snip-why' : undefined" @click="confirm">
          {{ busy === "confirm" ? "Keeping…" : "Use this table" }}
        </Button>
      </div>
    </template>

    <details class="rounded-md border px-2 py-1.5 text-sm">
      <summary class="cursor-pointer text-sm font-medium">Fund list ({{ snip?.include.length ?? 0 }} funds)</summary>
      <div class="mt-1.5 space-y-1.5">
        <label for="fund-list-text" class="text-xs text-muted-foreground">The funds the report's table uses, one name a line. Pasting the whole list replaces it.</label>
        <textarea id="fund-list-text" v-model="listDraft" rows="8" :class="[FIELD, 'h-auto w-full py-2 font-mono text-xs']"></textarea>
        <Button variant="outline" size="sm" :disabled="busy !== null" @click="saveList">{{ busy === "list" ? "Saving…" : "Save the list" }}</Button>
      </div>
    </details>

    <p v-if="kept" role="status" class="text-sm font-medium">{{ kept }}</p>
    <Notice v-if="problem" role="alert" class="font-medium whitespace-pre-line">{{ problem }}</Notice>
  </section>
</template>
