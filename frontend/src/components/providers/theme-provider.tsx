"use client";

import * as React from "react";

import { THEME_STORAGE_KEY } from "@/lib/theme-script";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export { THEME_STORAGE_KEY } from "@/lib/theme-script";

interface ThemeContextValue {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemePreference) => void;
  toggleTheme: () => void;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

function readStoredPreference(): ThemePreference {
  try {
    const v = window.localStorage.getItem(THEME_STORAGE_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(resolved: ResolvedTheme) {
  const root = document.documentElement;
  // Avoid transitions flashing while switching themes.
  root.classList.add("theme-switching");
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  root.dataset.theme = resolved;
  window.requestAnimationFrame(() => root.classList.remove("theme-switching"));
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<ThemePreference>("system");
  const [resolvedTheme, setResolvedTheme] = React.useState<ResolvedTheme>("light");
  // False until the stored preference has been read (avoids re-applying "system" on first paint).
  const [hydrated, setHydrated] = React.useState(false);

  // Hydrate from storage / DOM (already applied before paint by the init script).
  React.useEffect(() => {
    setThemeState(readStoredPreference());
    setResolvedTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
    setHydrated(true);
  }, []);

  // Apply the preference and follow system changes while on "system".
  React.useEffect(() => {
    if (!hydrated) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const resolve = () => {
      const next: ResolvedTheme = theme === "system" ? (mq.matches ? "dark" : "light") : theme;
      setResolvedTheme(next);
      applyTheme(next);
    };
    resolve();
    if (theme !== "system") return;
    mq.addEventListener("change", resolve);
    return () => mq.removeEventListener("change", resolve);
  }, [theme, hydrated]);

  // Sync across tabs.
  React.useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === THEME_STORAGE_KEY) setThemeState(readStoredPreference());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setTheme = React.useCallback((next: ThemePreference) => {
    setThemeState(next);
    try {
      if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // storage unavailable (private mode): keep in-memory preference
    }
  }, []);

  const toggleTheme = React.useCallback(() => {
    const current = theme === "system" ? (systemPrefersDark() ? "dark" : "light") : theme;
    setTheme(current === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  const value = React.useMemo(
    () => ({ theme, resolvedTheme, setTheme, toggleTheme }),
    [theme, resolvedTheme, setTheme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within <ThemeProvider>");
  return ctx;
}
