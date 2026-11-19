import { computed, ref, toValue, type MaybeRefOrGetter } from "vue";
import * as api from "./api";
import type { SnipMeta, SnipsListing } from "./types";

/** One week's snips and every action on them, held once for the page: the old Real Estate start screen and the prepare
 *  page's snip steps both draw from it, so a snip is read once however many sectors are on screen. */
export function useSnips(week: MaybeRefOrGetter<string>, onChange?: (listing: SnipsListing) => void) {
  const listing = ref<SnipsListing | null>(null);
  const error = ref<string | null>(null);
  // The text typed in each snip's box, by image hash; saved when the snip is confirmed or its sector or date changes.
  const drafts = ref<Record<string, string>>({});
  const busy = ref<Record<string, string>>({}); // hash -> what it is doing ("Reading…", "Confirming…")
  const uploading = ref(false);

  function take(next: SnipsListing) {
    listing.value = next;
    for (const s of next.snips) if (s.text !== null && !(s.hash in drafts.value)) drafts.value[s.hash] = s.text;
    onChange?.(next);
  }
  async function run<T>(hash: string, label: string, fn: () => Promise<T>): Promise<T | undefined> {
    busy.value[hash] = label;
    error.value = null;
    try {
      return await fn();
    } catch (err) {
      error.value = (err as api.ApiError).message;
    } finally {
      delete busy.value[hash];
    }
  }
  async function load() {
    try {
      take(await api.getSnips(toValue(week)));
      for (const s of listing.value?.snips ?? []) if (s.text === null) await read(s.hash); // one at a time: one vision call at once from here
    } catch (err) {
      error.value = (err as api.ApiError).message;
    }
  }
  async function upload(sector: string, files: FileList | null) {
    if (!files?.length) return;
    uploading.value = true;
    error.value = null;
    const added: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const before = new Set((listing.value?.snips ?? []).map((s) => s.hash));
        const next = await api.uploadSnip(toValue(week), sector, file);
        take(next);
        added.push(...next.snips.filter((s) => !before.has(s.hash)).map((s) => s.hash));
      } catch (err) {
        error.value = `${file.name}: ${(err as api.ApiError).message}`;
      }
    }
    uploading.value = false;
    for (const h of added) await read(h);
  }
  async function read(hash: string) {
    const pdf = listing.value?.snips.find((s) => s.hash === hash)?.kind === "pdf";
    const next = await run(hash, pdf ? "Reading the PDF…" : "Reading the image…", () => api.readSnip(toValue(week), hash));
    if (next) take(next);
  }
  async function move(s: SnipMeta, sector: string) {
    const next = await run(s.hash, "Moving…", () => api.changeSnip(toValue(week), s.hash, { sector }));
    if (next) take(next);
  }
  async function setDate(s: SnipMeta, date: string) {
    const next = await run(s.hash, "Saving…", () => api.changeSnip(toValue(week), s.hash, { date }));
    if (next) take(next);
  }
  async function confirm(s: SnipMeta) {
    const next = await run(s.hash, "Confirming…", async () => {
      if ((drafts.value[s.hash] ?? "") !== (s.text ?? "")) await api.changeSnip(toValue(week), s.hash, { text: drafts.value[s.hash] });
      return api.confirmSnip(toValue(week), s.hash);
    });
    if (next) take(next);
    else take(await api.getSnips(toValue(week))); // a refused confirm may still have saved the text: show what the server holds
  }
  async function remove(s: SnipMeta) {
    const next = await run(s.hash, "Removing…", () => api.removeSnip(toValue(week), s.hash));
    if (next) {
      delete drafts.value[s.hash];
      take(next);
    }
  }
  const bySector = computed(() =>
    (listing.value?.sectors ?? []).map((sec) => ({ ...sec, snips: (listing.value?.snips ?? []).filter((s) => s.sector === sec.id) })),
  );
  return { listing, error, drafts, busy, uploading, bySector, load, upload, read, move, setDate, confirm, remove };
}
export type Snips = ReturnType<typeof useSnips>;
