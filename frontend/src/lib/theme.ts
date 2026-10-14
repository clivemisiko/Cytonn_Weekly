/**
 * The colour theme: Light, Dark, or System (follow the device). The choice lives in one place, the `data-theme`
 * attribute on <html>: absent means System, and globals.css resolves every token from it. Browser storage only
 * remembers the choice across reloads, so if storage is empty, blocked or throws, the page still renders (as System)
 * and the toggle still works for the visit.
 */
export const THEMES = ["light", "dark", "system"] as const;
export type ThemeChoice = (typeof THEMES)[number];

export const THEME_KEY = "cytonn-theme";

/**
 * Runs inline, before the first paint (app/layout.tsx), so a reload never shows the wrong theme first. It only
 * restores a stored Light or Dark; anything else, or a storage that throws, leaves System.
 */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

const listeners = new Set<() => void>();

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The choice in force, read from the page itself (never from storage). */
export function currentTheme(): ThemeChoice {
  const set = document.documentElement.dataset.theme;
  return set === "light" || set === "dark" ? set : "system";
}

export function setTheme(choice: ThemeChoice): void {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  try {
    if (choice === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Storage is unavailable (private window, blocked site data): the theme applies for this visit only.
  }
  listeners.forEach((listener) => listener());
}
