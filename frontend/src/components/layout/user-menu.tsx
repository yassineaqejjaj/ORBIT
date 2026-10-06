"use client";

import Link from "next/link";
import { FolderKanban, LogOut, ShieldCheck } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { UserAvatar } from "@/components/domain/user-avatar";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useLogout, useMe } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

export interface UserMenuProps {
  /** "header": avatar button. "sidebar": avatar, name and role (sidebar footer). */
  variant?: "header" | "sidebar";
  /** Sidebar collapsed to icons: avatar only, name in a tooltip. */
  collapsed?: boolean;
  /** Role line under the name (sidebar variant), e.g. the project role. */
  roleLabel?: string;
}

/** User menu: identity, clearance, logout. */
export function UserMenu({ variant = "header", collapsed = false, roleLabel }: UserMenuProps) {
  const { data: me } = useMe();
  const logout = useLogout();
  if (!me) return null;
  const role = roleLabel ?? (me.is_admin ? "Administrateur" : undefined);
  const trigger =
    variant === "sidebar" ? (
      <button
        type="button"
        className={cn(
          "flex items-center gap-2.5 rounded-lg text-left transition-colors duration-150 hover:bg-surface-2/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
          collapsed ? "mx-auto size-10 justify-center" : "w-full px-2 py-1.5",
        )}
        aria-label={`Menu utilisateur — ${me.full_name}`}
      >
        <UserAvatar user={me} size="md" />
        {collapsed ? null : (
          <span className="grid min-w-0 flex-1 leading-tight">
            <span className="truncate text-[13px] font-medium text-foreground">{me.full_name}</span>
            {role ? <span className="truncate text-[11.5px] text-subtle-foreground">{role}</span> : null}
          </span>
        )}
      </button>
    ) : (
      <button
        type="button"
        className="flex items-center rounded-full p-0.5 transition-shadow hover:ring-2 hover:ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`Menu utilisateur — ${me.full_name}`}
      >
        <UserAvatar user={me} size="md" />
      </button>
    );
  return (
    <DropdownMenu>
      {collapsed ? (
        <SimpleTooltip content={me.full_name} side="right">
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
        </SimpleTooltip>
      ) : (
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      )}
      <DropdownMenuContent
        align={variant === "sidebar" ? "start" : "end"}
        side={variant === "sidebar" ? (collapsed ? "right" : "top") : "bottom"}
        className="w-72"
      >
        <div className="flex items-start gap-3 px-2 py-2.5">
          <UserAvatar user={me} size="lg" />
          <div className="grid min-w-0 gap-1">
            <p className="truncate text-sm font-semibold leading-tight">{me.full_name}</p>
            <p className="truncate text-xs text-muted-foreground">{me.email}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <ClassificationBadge level={me.clearance} prefix="Habilitation" noTooltip />
              {me.is_admin ? (
                <Badge tone="violet" icon={<ShieldCheck aria-hidden />}>
                  Administrateur
                </Badge>
              ) : null}
            </div>
          </div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/projects">
            <FolderKanban aria-hidden />
            Tous les projets
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => logout.mutate()} disabled={logout.isPending}>
          <LogOut aria-hidden />
          Se déconnecter
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
