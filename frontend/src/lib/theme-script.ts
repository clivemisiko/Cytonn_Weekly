export const THEME_KEY = "cytonn-theme";

/**
 * Runs inline, before the first paint (vite.config.ts puts it in the <head> of index.html), so a reload never shows the wrong theme first. It only
 * restores a stored Light or Dark; anything else, or a storage that throws, leaves System.
 */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
