import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Reads the colour tokens out of styles.css itself, so a changed token that loses contrast fails here.
const css = readFileSync(new URL("../styles.css", import.meta.url), "utf-8");
type Theme = "light" | "dark";

function token(name: string, theme: Theme): string {
  const m = new RegExp(`--${name}:\s*([^;]+);`).exec(css);
  if (!m) throw new Error(`token --${name} not found`);
  const v = m[1]!.replace(/\/\*.*?\*\//g, "").trim();
  const pair = /^light-dark\(\s*(#[0-9a-f]{6})\s*,\s*(#[0-9a-f]{6})\s*\)$/i.exec(v);
  if (pair) return (theme === "light" ? pair[1] : pair[2])!;
  if (/^#[0-9a-f]{6}$/i.test(v)) return v;
  throw new Error(`token --${name} is not a hex colour or light-dark(hex, hex): ${v}`);
}

const channels = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const luminance = (hex: string) => {
  const [r, g, b] = channels(hex).map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
};
export const ratio = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};
/** `top` at `pct` percent over `base`, in sRGB: what bg-<state>/10 looks like on a card. */
const mix = (top: string, base: string, pct: number) =>
  "#" + channels(top).map((c, i) => Math.round((c * pct + channels(base)[i]! * (100 - pct)) / 100).toString(16).padStart(2, "0")).join("");

type Pair = { what: string; fg: (t: Theme) => string; bg: (t: Theme) => string; min: number };
const T = (n: string) => (t: Theme) => token(n, t);
const tint = (state: string, base = "card", pct = 10) => (t: Theme) => mix(token(state, t), token(base, t), pct);

const TEXT = 4.5;
const EDGE = 3;
export const PAIRS: Pair[] = [
  { what: "ink on card", fg: T("foreground"), bg: T("card"), min: TEXT },
  { what: "ink on page", fg: T("foreground"), bg: T("background"), min: TEXT },
  { what: "body grey (muted text) on card", fg: T("muted-foreground"), bg: T("card"), min: TEXT },
  { what: "muted text on page", fg: T("muted-foreground"), bg: T("background"), min: TEXT },
  { what: "disabled primary button: its label on its grey fill", fg: T("muted-foreground"), bg: T("muted"), min: TEXT },
  { what: "muted text on the muted fill", fg: T("muted-foreground"), bg: T("muted"), min: TEXT },
  { what: "link on card", fg: T("link"), bg: T("card"), min: TEXT },
  { what: "link on page", fg: T("link"), bg: T("background"), min: TEXT },
  { what: "link on the selected tint", fg: T("accent-foreground"), bg: T("accent"), min: TEXT },
  { what: "primary text on the brand green", fg: T("primary-foreground"), bg: T("primary"), min: TEXT },
  { what: "top bar ink on top bar", fg: T("band-foreground"), bg: T("band"), min: TEXT },
  { what: "top bar muted on top bar", fg: T("band-muted"), bg: T("band"), min: TEXT },
  { what: "flag text on its tint", fg: T("flag-fg"), bg: tint("flag"), min: TEXT },
  { what: "warn text on its tint", fg: T("warn-fg"), bg: tint("warn"), min: TEXT },
  { what: "ok text on its tint", fg: T("ok-fg"), bg: tint("ok"), min: TEXT },
  { what: "flag text on card", fg: T("flag-fg"), bg: T("card"), min: TEXT },
  { what: "warn text on card", fg: T("warn-fg"), bg: T("card"), min: TEXT },
  { what: "ok text on card", fg: T("ok-fg"), bg: T("card"), min: TEXT },
  { what: "text on the solid flag fill", fg: T("flag-on"), bg: T("flag"), min: TEXT },
  { what: "text on the solid ok fill", fg: T("ok-on"), bg: T("ok"), min: TEXT },
  { what: "control edge on card", fg: T("input"), bg: T("card"), min: EDGE },
  { what: "control edge on page", fg: T("input"), bg: T("background"), min: EDGE },
  { what: "control edge on the muted fill", fg: T("input"), bg: T("muted"), min: EDGE },
  { what: "focus ring on card", fg: T("ring"), bg: T("card"), min: EDGE },
  { what: "focus ring on page", fg: T("ring"), bg: T("background"), min: EDGE },
];

describe("colour contrast of the tokens in styles.css (WCAG)", () => {
  for (const theme of ["light", "dark"] as const)
    for (const p of PAIRS)
      it(`${theme}: ${p.what} is at least ${p.min}:1`, () => {
        expect(ratio(p.fg(theme), p.bg(theme))).toBeGreaterThanOrEqual(p.min);
      });

  it("the brand green is never used as text or an edge: it is only the primary fill", () => {
    for (const n of ["link", "ring", "input", "accent-foreground", "muted-foreground", "ok-fg"]) {
      expect(token(n, "light").toLowerCase()).not.toBe("#49b315");
    }
  });

  it("ok is a different colour from the brand green in both themes", () => {
    for (const t of ["light", "dark"] as const) expect(token("ok", t).toLowerCase()).not.toBe("#49b315");
  });
});
