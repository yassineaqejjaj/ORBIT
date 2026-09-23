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
  /** Custom breadcrumb labels keyed by route segment value (e.g. a document id → its title). */
  crumbLabels: Record<string, string>;
  setCrumbLabel: (key: string, label: string | null) => void;
}

const ShellContext = React.createContext<ShellContextValue | null>(null);

export function ShellProvider({ children }: { children: React.ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = React.useState(false);
  const [createProjectOpen, setCreateProjectOpen] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [crumbLabels, setCrumbLabels] = React.useState<Record<string, string>>({});

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
      crumbLabels,
      setCrumbLabel,
    }),
    [commandPaletteOpen, createProjectOpen, mobileNavOpen, crumbLabels, setCrumbLabel],
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
