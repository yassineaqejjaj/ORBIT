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
import { useLogout, useMe } from "@/lib/api/hooks";

/** Header user menu: identity, clearance, logout. */
export function UserMenu() {
  const { data: me } = useMe();
  const logout = useLogout();
  if (!me) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center rounded-full p-0.5 transition-shadow hover:ring-2 hover:ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Menu utilisateur — ${me.full_name}`}
        >
          <UserAvatar user={me} size="md" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
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
