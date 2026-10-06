"use client";

import * as React from "react";

interface ShellContextValue {
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
  openCreateProject: () => void;
  createProjectOpen: boolean;
  setCreateProjectOpen: (open: boolean) => void;
  mobileNavOpen: boolean;
  setMobileNavOpen: (open: boolean) => void;
  /** Desktop sidebar collapsed to 64 px (remembered, toggled with ⌘\ / Ctrl+\). */
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  /** Custom breadcrumb labels keyed by route segment value (e.g. a document id → its title). */
  crumbLabels: Record<string, string>;
  setCrumbLabel: (key: string, label: string | null) => void;
}

const ShellContext = React.createContext<ShellContextValue | null>(null);

const SIDEBAR_STORAGE_KEY = "orbit.sidebar.collapsed";

function readSidebarCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeSidebarCollapsed(collapsed: boolean) {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
  } catch {
    // Storage unavailable (private mode, blocked site data): the state simply isn't remembered.
  }
}

export function ShellProvider({ children }: { children: React.ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = React.useState(false);
  const [createProjectOpen, setCreateProjectOpen] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [crumbLabels, setCrumbLabels] = React.useState<Record<string, string>>({});
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);

  React.useEffect(() => setSidebarCollapsed(readSidebarCollapsed()), []);

  const toggleSidebar = React.useCallback(() => {
    setSidebarCollapsed((prev) => {
      writeSidebarCollapsed(!prev);
      return !prev;
    });
  }, []);

  // ⌘\ (macOS) / Ctrl+\ toggles the desktop sidebar.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      // `key` covers layouts where "\\" needs a modifier (AZERTY); `code` covers the US physical key.
      const isBackslash = event.key === "\\" || (event.code === "Backslash" && !event.altKey && !event.shiftKey);
      if (!isBackslash) return;
      event.preventDefault();
      toggleSidebar();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleSidebar]);

  const setCrumbLabel = React.useCallback((key: string, label: string | null) => {
    setCrumbLabels((prev) => {
      if (label === null) {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      }
      if (prev[key] === label) return prev;
      return { ...prev, [key]: label };
    });
  }, []);

  const value = React.useMemo<ShellContextValue>(
    () => ({
      openCommandPalette: () => setCommandPaletteOpen(true),
      closeCommandPalette: () => setCommandPaletteOpen(false),
      commandPaletteOpen,
      setCommandPaletteOpen,
      openCreateProject: () => setCreateProjectOpen(true),
      createProjectOpen,
      setCreateProjectOpen,
      mobileNavOpen,
      setMobileNavOpen,
      sidebarCollapsed,
      toggleSidebar,
      crumbLabels,
      setCrumbLabel,
    }),
    [commandPaletteOpen, createProjectOpen, mobileNavOpen, sidebarCollapsed, toggleSidebar, crumbLabels, setCrumbLabel],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell(): ShellContextValue {
  const ctx = React.useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within <ShellProvider>");
  return ctx;
}

/**
 * Sets a human label for a dynamic route segment in the header breadcrumb while mounted.
 * Example (document page): useBreadcrumbLabel(documentId, document?.title)
 */
export function useBreadcrumbLabel(segmentValue: string | undefined, label: string | null | undefined) {
  const ctx = React.useContext(ShellContext);
  const setCrumbLabel = ctx?.setCrumbLabel;
  React.useEffect(() => {
    if (!setCrumbLabel || !segmentValue || !label) return;
    setCrumbLabel(segmentValue, label);
    return () => setCrumbLabel(segmentValue, null);
  }, [setCrumbLabel, segmentValue, label]);
}
