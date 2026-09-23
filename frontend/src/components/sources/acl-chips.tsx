"use client";

import * as React from "react";
import { Crown, PencilLine, UserRound, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { Member } from "@/lib/api/types";
import { ACL_ALL_MEMBERS, aclPrincipalLabel } from "@/lib/enums";
import { cn } from "@/lib/utils";

export interface AclChipsProps {
  principals: readonly string[];
  /** Project members, used to resolve `user:<uuid>` names. */
  members?: readonly Member[];
  size?: "sm" | "md";
  /** Show at most N chips, then "+k". */
  max?: number;
  className?: string;
}

function iconFor(principal: string): React.ReactNode {
  if (principal === ACL_ALL_MEMBERS) return <Users aria-hidden />;
  if (principal === "role:owner") return <Crown aria-hidden />;
  if (principal.startsWith("role:")) return <PencilLine aria-hidden />;
  return <UserRound aria-hidden />;
}

/** Human-readable ACL principals (Tous les membres · Éditeurs et propriétaires · Camille Martin…). */
export function AclChips({ principals, members, size = "sm", max, className }: AclChipsProps) {
  const names = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const m of members ?? []) map[m.user.id] = m.user.full_name || m.user.email;
    return map;
  }, [members]);

  const list = principals.length > 0 ? principals : [ACL_ALL_MEMBERS];
  const shown = typeof max === "number" ? list.slice(0, max) : list;
  const rest = list.length - shown.length;
  const restricted = !list.includes(ACL_ALL_MEMBERS);

  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1", className)}>
      {shown.map((p) => (
        <Badge key={p} size={size} tone={restricted ? "violet" : "neutral"} variant="outline" icon={iconFor(p)} title={p}>
          {aclPrincipalLabel(p, names)}
        </Badge>
      ))}
      {rest > 0 ? (
        <SimpleTooltip content={list.slice(shown.length).map((p) => aclPrincipalLabel(p, names)).join(", ")}>
          <span className="inline-flex">
            <Badge size={size} variant="outline">
              +{rest}
            </Badge>
          </span>
        </SimpleTooltip>
      ) : null}
    </span>
  );
}
