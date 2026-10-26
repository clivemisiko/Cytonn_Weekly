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
