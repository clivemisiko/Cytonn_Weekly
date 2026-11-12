import type { SnipMeta, SnipsListing } from "./types";

const UNCLEAR = /\[unclear[^\]]*\]/i;

/** Whether the text still holds an [unclear] mark: a snip with one cannot be confirmed (the API refuses it too). */
export const hasUnclear = (text: string) => UNCLEAR.test(text);

/** What a snip's card says, in words: never colour alone. `typed` is what is in its text box now. */
export function snipStatus(s: SnipMeta, typed?: string): string {
  if (s.text === null) return "Not read yet";
  if (s.confirmed && typed !== undefined && typed !== s.text) return "Changed, confirm again";
  if (s.confirmed) return "Confirmed";
  return hasUnclear(typed ?? s.text) ? "Unconfirmed: has [unclear] marks" : "Unconfirmed";
}

export function snipCounts(listing: SnipsListing) {
  const confirmed = listing.snips.filter((s) => s.confirmed).length;
  const sectors = listing.sectors.map((sec) => ({ id: sec.id, label: sec.label, confirmed: listing.snips.filter((s) => s.sector === sec.id && s.confirmed).length }));
  return { confirmed, unconfirmed: listing.snips.length - confirmed, without: sectors.filter((s) => s.confirmed === 0).map((s) => s.label) };
}

/** The list of unconfirmed snips by sector, or null when every uploaded snip is confirmed. An unconfirmed snip is not used. */
export function unconfirmedNote(listing: SnipsListing): string | null {
  const by = listing.sectors
    .map((sec) => [sec.label, listing.snips.filter((s) => s.sector === sec.id && !s.confirmed).length] as const)
    .filter(([, n]) => n > 0);
  if (!by.length) return null;
  const total = by.reduce((n, [, k]) => n + k, 0);
  return `${total} unconfirmed ${total === 1 ? "snip" : "snips"} (${by.map(([l, n]) => `${l}: ${n}`).join(", ")}). Unconfirmed snips are not used in the draft.`;
}
