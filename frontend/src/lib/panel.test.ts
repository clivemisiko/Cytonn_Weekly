import { describe, expect, it } from "vitest";
import { readPanelOpen, writePanelOpen, type PanelStorage } from "./panel";

const memory = (): PanelStorage & { held: Record<string, string> } => {
  const held: Record<string, string> = {};
  return { held, getItem: (k) => held[k] ?? null, setItem: (k, v) => void (held[k] = v) };
};
const broken: PanelStorage = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};

describe("side panel state", () => {
  it("is open when nothing is remembered, and remembers each panel on its own", () => {
    const storage = memory();
    expect(readPanelOpen("overview", storage)).toBe(true);
    writePanelOpen("overview", false, storage);
    expect(readPanelOpen("overview", storage)).toBe(false);
    expect(readPanelOpen("another", storage)).toBe(true);
    writePanelOpen("overview", true, storage);
    expect(readPanelOpen("overview", storage)).toBe(true);
  });

  it("works without storage: open, and a write that fails is not an error", () => {
    expect(readPanelOpen("overview", null)).toBe(true);
    expect(readPanelOpen("overview", broken)).toBe(true);
    expect(() => writePanelOpen("overview", false, broken)).not.toThrow();
    expect(() => writePanelOpen("overview", false, null)).not.toThrow();
  });
});
