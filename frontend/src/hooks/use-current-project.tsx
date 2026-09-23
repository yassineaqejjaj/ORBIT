"use client";

import * as React from "react";

import { useMe } from "@/lib/api/hooks";
import type { Project } from "@/lib/api/types";
import { hasMinRole, type Role } from "@/lib/enums";

export interface CurrentProjectValue {
  project: Project;
  slug: string;
  /** Caller role in the project (admins are treated as owners). */
  role: Role;
  /** Raw role returned by the API. */
  memberRole: Role;
  isAdmin: boolean;
  /** True when the caller has at least `min`. */
  hasRole: (min: Role) => boolean;
  canEdit: boolean;
  isOwner: boolean;
}

const CurrentProjectContext = React.createContext<CurrentProjectValue | null>(null);

/** Provides the current project (resolved by `app/(app)/projects/[slug]/layout.tsx`). */
export function CurrentProjectProvider({ project, children }: { project: Project; children: React.ReactNode }) {
  const { data: me } = useMe();
  const isAdmin = Boolean(me?.is_admin);
  const value = React.useMemo<CurrentProjectValue>(() => {
    const role: Role = isAdmin ? "owner" : project.role;
    return {
      project,
      slug: project.slug,
      role,
      memberRole: project.role,
      isAdmin,
      hasRole: (min: Role) => hasMinRole(role, min),
      canEdit: hasMinRole(role, "editor"),
      isOwner: hasMinRole(role, "owner"),
    };
  }, [project, isAdmin]);
  return <CurrentProjectContext.Provider value={value}>{children}</CurrentProjectContext.Provider>;
}

/** Current project + caller role. Must be used under /projects/[slug]/…. */
export function useCurrentProject(): CurrentProjectValue {
  const ctx = React.useContext(CurrentProjectContext);
  if (!ctx) throw new Error("useCurrentProject must be used within a project route (/projects/[slug]/…)");
  return ctx;
}

/** Same as useCurrentProject but returns null outside a project route. */
export function useOptionalCurrentProject(): CurrentProjectValue | null {
  return React.useContext(CurrentProjectContext);
}
