"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, ChevronsUpDown, FolderKanban, LayoutGrid, Plus } from "lucide-react";

import { RoleBadge } from "@/components/domain/enum-badge";
import { useShell } from "@/components/layout/shell-context";
import { projectHref } from "@/components/layout/nav";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useProject, useProjects } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

function ProjectGlyph({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={cn(
        "flex size-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-teal-500 to-teal-700 text-[12px] font-semibold uppercase text-white shadow-xs",
        className,
      )}
      aria-hidden
    >
      {name.trim().charAt(0) || "P"}
    </span>
  );
}

/** Sidebar dropdown to switch project or create a new one. */
export function ProjectSwitcher({ slug }: { slug?: string }) {
  const router = useRouter();
  const { openCreateProject } = useShell();
  const projects = useProjects();
  const current = useProject(slug);
  const currentName = current.data?.name ?? projects.data?.find((p) => p.slug === slug)?.name;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="group flex w-full items-center gap-2.5 rounded-lg border border-sidebar-border bg-background px-2 py-1.5 text-left shadow-xs transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Changer de projet"
        >
          {slug ? (
            currentName ? (
              <ProjectGlyph name={currentName} />
            ) : current.isError ? (
              <ProjectGlyph name="?" className="from-slate-400 to-slate-600" />
            ) : (
              <Skeleton className="size-7" />
            )
          ) : (
            <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-dashed border-border-strong text-muted-foreground">
              <FolderKanban className="size-3.5" aria-hidden />
            </span>
          )}
          <span className="grid min-w-0 flex-1 leading-tight">
            <span className="text-[10.5px] font-medium uppercase tracking-wider text-subtle-foreground">Projet</span>
            <span className="truncate text-[13px] font-semibold text-foreground">
              {slug ? (currentName ?? (current.isError ? "Projet indisponible" : "Chargement…")) : "Choisir un projet"}
            </span>
          </span>
          <ChevronsUpDown className="size-4 shrink-0 text-subtle-foreground group-hover:text-foreground" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[var(--radix-dropdown-menu-trigger-width)] min-w-64">
        <DropdownMenuLabel>Mes projets</DropdownMenuLabel>
        {projects.isPending ? (
          <div className="grid gap-1.5 p-2">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
          </div>
        ) : projects.isError ? (
          <p className="px-2 py-1.5 text-xs text-destructive">Impossible de charger les projets.</p>
        ) : projects.data.length === 0 ? (
          <p className="px-2 py-1.5 text-xs text-muted-foreground">Aucun projet pour le moment.</p>
        ) : (
          <div className="max-h-72 overflow-y-auto">
            {projects.data.map((p) => (
              <DropdownMenuItem key={p.id} onSelect={() => router.push(projectHref(p.slug))} className="gap-2.5">
                <ProjectGlyph name={p.name} className="size-6 text-[11px]" />
                <span className="grid min-w-0 flex-1 leading-tight">
                  <span className="truncate font-medium">{p.name}</span>
                  <span className="truncate font-mono text-[11px] text-subtle-foreground">{p.slug}</span>
                </span>
                {p.slug === slug ? (
                  <Check className="text-primary" aria-label="Projet actuel" />
                ) : (
                  <RoleBadge value={p.role} withIcon={false} />
                )}
              </DropdownMenuItem>
            ))}
          </div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/projects">
            <LayoutGrid aria-hidden />
            Tous les projets
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => openCreateProject()}>
          <Plus aria-hidden />
          Nouveau projet
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
