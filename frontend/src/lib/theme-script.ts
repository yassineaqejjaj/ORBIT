/**
 * Inline script executed before first paint (injected in <head> by the root layout)
 * to apply the stored/system theme without a flash of the wrong theme.
 * Kept in a plain module (not "use client") so the server layout can read the string.
 */
export const THEME_STORAGE_KEY = "orbit-theme";

export const themeInitScript = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(t!=="light"&&t!=="dark")t="system";var d=t==="dark"||(t==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);var r=document.documentElement;r.classList.toggle("dark",d);r.style.colorScheme=d?"dark":"light";r.dataset.theme=d?"dark":"light";}catch(e){}})();`;
