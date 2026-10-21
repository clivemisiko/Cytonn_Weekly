/**
 * Whether a side panel is open, remembered per panel in browser storage as a convenience for the person using it.
 * Like the theme, every read and write is in try/catch and the page works without storage (private window, blocked
 * site data): a panel is open unless the page was told, in this browser, to keep it shut.
 */
export type PanelStorage = Pick<Storage, "getItem" | "setItem">;

const keyOf = (name: string) => `cytonn-panel-${name}`;

function browserStorage(): PanelStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null; // even touching it can throw
  }
}

export function readPanelOpen(name: string, storage: PanelStorage | null = browserStorage()): boolean {
  try {
    return storage?.getItem(keyOf(name)) !== "closed";
  } catch {
    return true;
  }
}

export function writePanelOpen(name: string, open: boolean, storage: PanelStorage | null = browserStorage()): void {
  try {
    storage?.setItem(keyOf(name), open ? "open" : "closed");
  } catch {
    // Not remembered: the panel still opens and shuts for this visit.
  }
}
