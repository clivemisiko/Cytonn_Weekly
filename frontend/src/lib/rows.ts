export const ROWS_LABEL = "This week's rows (xlsx)";

/** The Friday a "Week ending YYYY-MM-DD" period names, or null for any other period (the rows are for one week). */
export const rowsWeek = (period: string): string | null => /^Week ending (\d{4}-\d{2}-\d{2})$/.exec(period)?.[1] ?? null;

/** What the analyst reads when the rows could not be built. 422 and 409 are the API's two refusals; the 409 carries its own reason. */
export function rowsMessage(status: number | null, detail: string): string {
  if (status === 422) return "That week is not one the report can use. Choose the Friday the week ends on, then try again.";
  if (status === 409) return `${detail.trim().replace(/\.?$/, ".")} Upload that workbook again or remove it, then try again.`;
  return detail;
}

/** The file name in a Content-Disposition header: the plain `filename="..."`, or the UTF-8 `filename*=` the server uses when a name has spaces or commas. */
export function fileNameOf(header: string | null, fallback: string): string {
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(header ?? "")?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      /* a name that is not valid percent-encoding: try the plain form */
    }
  }
  return /filename="([^"]+)"/.exec(header ?? "")?.[1] ?? fallback;
}
