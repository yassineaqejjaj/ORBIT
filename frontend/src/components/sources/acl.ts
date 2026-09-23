/**
 * ACL helpers for the Sources screens (ARCHITECTURE §3).
 * Maps the UI presets (whole project / editors+owners / owners / named users) to `acl_principals`.
 */
import { ACL_ALL_MEMBERS } from "@/lib/enums";

export type AclMode = "project" | "editors" | "owners" | "users";

export const ACL_MODE_OPTIONS: ReadonlyArray<{ value: AclMode; label: string; description: string }> = [
  { value: "project", label: "Tout le projet", description: "Tous les membres du projet (project:*)" },
  { value: "editors", label: "Éditeurs et propriétaires", description: "Membres ayant au moins le rôle éditeur" },
  { value: "owners", label: "Propriétaires", description: "Uniquement les propriétaires du projet" },
  { value: "users", label: "Utilisateurs nommés", description: "Liste nominative de membres" },
];

export interface AclValue {
  mode: AclMode;
  /** User ids when `mode === "users"`. */
  userIds: string[];
}

export const DEFAULT_ACL_VALUE: AclValue = { mode: "project", userIds: [] };

const USER_PREFIX = "user:";

/** UI value → API `acl_principals`. */
export function aclToPrincipals(value: AclValue): string[] {
  switch (value.mode) {
    case "editors":
      return ["role:editor"];
    case "owners":
      return ["role:owner"];
    case "users":
      return value.userIds.map((id) => `${USER_PREFIX}${id}`);
    default:
      return [ACL_ALL_MEMBERS];
  }
}

/** API `acl_principals` → UI value (best effort for mixed lists: the most permissive entry wins). */
export function principalsToAcl(principals: readonly string[] | null | undefined): AclValue {
  const list = principals ?? [];
  if (list.length === 0 || list.includes(ACL_ALL_MEMBERS)) return { mode: "project", userIds: [] };
  if (list.includes("role:viewer")) return { mode: "project", userIds: [] };
  if (list.includes("role:editor")) return { mode: "editors", userIds: [] };
  const userIds = list.filter((p) => p.startsWith(USER_PREFIX)).map((p) => p.slice(USER_PREFIX.length));
  if (list.includes("role:owner") && userIds.length === 0) return { mode: "owners", userIds: [] };
  if (userIds.length > 0) return { mode: "users", userIds };
  return { mode: "owners", userIds: [] };
}

/** True when the ACL value can be submitted (named users need at least one member). */
export function isAclValid(value: AclValue): boolean {
  return value.mode !== "users" || value.userIds.length > 0;
}

/** True when the ACL restricts access below "all project members". */
export function isRestrictedAcl(principals: readonly string[] | null | undefined): boolean {
  const list = principals ?? [];
  return list.length > 0 && !list.includes(ACL_ALL_MEMBERS) && !list.includes("role:viewer");
}

/** Normalize free-form tags (trim, dedupe, max 64 chars, max 50 tags — same rules as the API). */
export function normalizeTags(values: readonly string[]): string[] {
  const result: string[] = [];
  for (const raw of values) {
    const tag = raw.trim().slice(0, 64);
    if (tag && !result.includes(tag)) result.push(tag);
  }
  return result.slice(0, 50);
}
