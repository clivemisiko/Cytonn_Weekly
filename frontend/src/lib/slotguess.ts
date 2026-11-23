import { friendlyDate } from "./format";
import type { InputFile } from "./types";

/** The slot a dropped file goes to, from its name alone (the API then reads the file and refuses a wrong one).
 *  A bank's results PDF is tried before the equities workbook ("equity-group-results.pdf" would otherwise match "equit"),
 *  and never takes a KCB "daily" or "weekly" report or a CBK file. Only slugs in `available` are returned; without bank_results among them the old rules decide, as before. */
export function guessSlot(filename: string, available?: string[]): string | null {
  const banks = !available || available.includes("bank_results");
  const got = guess(filename.toLowerCase(), banks);
  return got && (!available || available.includes(got)) ? got : null;
}

function guess(lower: string, banks: boolean): string | null {
  const pdf = lower.endsWith(".pdf");
  if (banks && pdf && /financial[-_ ]?statements|unaudited[-_ ]?financial[-_ ]?results|results/.test(lower) && !/daily|weekly|cbk|bulletin/.test(lower)) {
    return "bank_results";
  }
  if (lower.includes("fixed") || lower.includes("fi_") || (lower.includes("income") && lower.endsWith(".xlsx"))) return "fi_workbook";
  if (lower.includes("equit") || lower.includes("eq_")) return "equities_workbook";
  if (lower.includes("digital") || lower.includes("payment") || lower.includes("dp_")) return "dp_workbook";
  if (lower.includes("bulletin") || lower.includes("cbk")) return "cbk_bulletin";
  if (lower.includes("nse") || lower.includes("yield")) return "nse_yield_curve";
  if (lower.includes("daily")) return "kcb_daily";
  if (lower.includes("weekly") && pdf) return "kcb_weekly";
  return null;
}

export interface BankRow {
  key: string;
  bank: string;
  period: string;
  status: string;
  tone: "ok" | "warn" | "bad";
  flags: string[];
  /** Kept on the server: it can be replaced and removed. */
  stored: string | null;
}

/** One row per stored bank file, then one per refused file (those are not kept, so only this page knows them). */
export function bankRows(files: InputFile[], refused: { name: string; reason: string }[]): BankRow[] {
  const kept = files.map((f): BankRow => {
    const r = f.read;
    const n = r?.flag_count ?? 0;
    return {
      key: f.stored_name,
      bank: r?.bank ?? f.original_name,
      period: f.read_date ? `Period ended ${friendlyDate(f.read_date)}` : "Period not read",
      status: n ? `Read with ${n} ${n === 1 ? "flag" : "flags"}` : "Read OK",
      tone: n ? "warn" : "ok",
      flags: r?.flags ?? [],
      stored: f.stored_name,
    };
  });
  return [...kept, ...refused.map((x, i): BankRow => ({ key: `refused-${i}`, bank: x.name, period: "", status: `Refused: ${x.reason}`, tone: "bad", flags: [], stored: null }))];
}
