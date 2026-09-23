"use client";

import * as React from "react";

import { useOptionalCurrentProject } from "@/hooks/use-current-project";
import { hasMinRole, type Role } from "@/lib/enums";

export interface RequireRoleProps {
  /** Minimum project role required to render `children`. */
  min: Role;
  /** Rendered when the caller lacks the role (default: nothing). */
  fallback?: React.ReactNode;
  /** Explicit role (defaults to the current project's caller role). */
  role?: Role | null;
  children: React.ReactNode;
}

/**
 * Hides UI the caller is not allowed to use: <RequireRole min="editor"><Button>Importer</Button></RequireRole>.
 * UI-only convenience — the API enforces permissions server-side.
 */
export function RequireRole({ min, fallback = null, role, children }: RequireRoleProps) {
  const ctx = useOptionalCurrentProject();
  const effective = role ?? ctx?.role ?? null;
  return <>{hasMinRole(effective, min) ? children : fallback}</>;
}

/** Hook variant: `const canEdit = useHasRole("editor")`. */
export function useHasRole(min: Role): boolean {
  const ctx = useOptionalCurrentProject();
  return hasMinRole(ctx?.role ?? null, min);
}
