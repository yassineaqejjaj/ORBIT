import Link from "next/link";
import { ArrowUpRight, Brain, Database, FileText, Telescope } from "lucide-react";

import { RoleBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { projectHref } from "@/components/layout/nav";
import { Skeleton } from "@/components/ui/skeleton";
import type { ProjectSummary } from "@/lib/api/types";
import { formatCompact } from "@/lib/format";

function Stat({ icon: Icon, label, value, title }: { icon: typeof Database; label: string; value: number; title?: string }) {
  return (
    <div className="grid min-w-0 gap-0.5" title={title}>
      <dt className="flex min-w-0 items-center gap-1 text-[11px] text-muted-foreground">
        <Icon className="size-3 shrink-0" aria-hidden />
        <span className="truncate">{label}</span>
      </dt>
      <dd className="text-[15px] font-semibold tabular-nums text-foreground">{formatCompact(value)}</dd>
    </div>
  );
}

/** Card for a ProjectSummary (projects list). */
export function ProjectCard({ project }: { project: ProjectSummary }) {
  const s = project.stats;
  return (
    <Link
      href={projectHref(project.slug)}
      className="group relative flex h-full flex-col rounded-xl border border-border bg-card p-5 shadow-xs transition-[border-color,box-shadow] duration-200 hover:border-border-strong hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-start gap-3">
        <span
          className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft ring-1 ring-inset ring-accent-coral/20 text-base font-semibold uppercase text-accent-text shadow-xs"
          aria-hidden
        >
          {project.name.trim().charAt(0) || "P"}
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <div className="flex min-w-0 items-start gap-2">
            <h2 className="line-clamp-2 min-w-0 break-words text-[15px] font-semibold leading-snug tracking-tight text-foreground">
              {project.name}
            </h2>
            <ArrowUpRight
              className="mt-0.5 size-4 shrink-0 text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100"
              aria-hidden
            />
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <p className="min-w-0 truncate font-mono text-xs text-subtle-foreground">{project.slug}</p>
            <RoleBadge value={project.role} />
          </div>
        </div>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.5rem] text-[13px] leading-relaxed text-muted-foreground">
        {project.description?.trim() || "Aucune description."}
      </p>

      <dl className="mt-4 grid grid-cols-4 gap-3 border-t border-border pt-4">
        <Stat icon={Database} label="Sources" value={s.sources} />
        <Stat icon={FileText} label="Docs" value={s.documents} title="Documents ingérés" />
        <Stat icon={Brain} label="Mémoire" value={s.memory_items} />
        <Stat icon={Telescope} label="Contextes" value={s.context_requests_7d} title="Contextes servis sur les 7 derniers jours" />
      </dl>

      <p className="mt-4 text-[11.5px] text-subtle-foreground">
        Mis à jour <RelativeTime date={project.updated_at} />
      </p>
    </Link>
  );
}

export function ProjectCardSkeleton() {
  return (
    <div className="flex flex-col rounded-xl border border-border bg-card p-5" aria-hidden>
      <div className="flex items-start gap-3">
        <Skeleton className="size-10 rounded-lg" />
        <div className="grid flex-1 gap-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
      <Skeleton className="mt-4 h-3.5 w-full" />
      <Skeleton className="mt-2 h-3.5 w-4/5" />
      <div className="mt-5 grid grid-cols-4 gap-3 border-t border-border pt-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="grid gap-1.5">
            <Skeleton className="h-2.5 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ))}
      </div>
    </div>
  );
}
