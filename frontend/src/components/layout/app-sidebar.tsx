"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGrid } from "lucide-react";

import { ConstellationDots, OrbitLogo } from "@/components/brand/orbit-logo";
import { activeProjectNav, PROJECT_NAV, projectHref } from "@/components/layout/nav";
import { ProjectSwitcher } from "@/components/layout/project-switcher";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useInboxCount } from "@/lib/api/features-feed";
import { useMeta, useProject } from "@/lib/api/hooks";
import { hasMinRole } from "@/lib/enums";
import { cn } from "@/lib/utils";

function NavLink({
  href,
  active,
  icon: Icon,
  label,
  onNavigate,
  badge,
  badgeLabel,
}: {
  href: string;
  active: boolean;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  label: string;
  onNavigate?: () => void;
  /** Counter shown on the right (hidden when 0 or undefined). */
  badge?: number;
  badgeLabel?: string;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
      )}
    >
      {active ? <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-brand" aria-hidden /> : null}
      <Icon
        className={cn("size-4 shrink-0", active ? "text-brand" : "text-sidebar-muted group-hover:text-sidebar-foreground")}
        aria-hidden
      />
      <span className="truncate">{label}</span>
      {badge ? (
        <span
          className="ml-auto inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-brand-soft px-1.5 text-[10.5px] font-semibold tabular-nums text-brand"
          aria-label={badgeLabel}
          title={badgeLabel}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </Link>
  );
}

function SystemStatus() {
  const meta = useMeta();
  const ok = meta.isSuccess;
  const label = meta.isPending ? "Connexion…" : ok ? "Plateforme opérationnelle" : "API injoignable";
  const detail = ok
    ? `Version ${meta.data.version} · ${meta.data.embedding_model} · reranker ${meta.data.reranker}${meta.data.llm ? ` · LLM ${meta.data.llm}` : " · mode déterministe"}`
    : meta.isError
      ? "Le backend ORBIT ne répond pas."
      : undefined;
  return (
    <SimpleTooltip content={detail} side="top" align="start">
      <div className="flex items-center gap-2 text-[11.5px] text-sidebar-muted" tabIndex={detail ? 0 : -1}>
        <span className="relative flex size-2" aria-hidden>
          {ok ? <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-40" /> : null}
          <span
            className={cn(
              "relative inline-flex size-2 rounded-full",
              meta.isPending ? "bg-slate-400" : ok ? "bg-emerald-500" : "bg-red-500",
            )}
          />
        </span>
        <span className="truncate">{label}</span>
        {ok ? <span className="ml-auto font-mono text-[10.5px]">v{meta.data.version}</span> : null}
      </div>
    </SimpleTooltip>
  );
}

export interface SidebarContentProps {
  slug?: string;
  /** Called after a navigation (closes the mobile sheet). */
  onNavigate?: () => void;
}

/** Sidebar body (used by the desktop aside and the mobile sheet). */
export function SidebarContent({ slug, onNavigate }: SidebarContentProps) {
  const pathname = usePathname();
  const project = useProject(slug);
  const active = slug ? activeProjectNav(pathname, slug) : undefined;
  const role = project.data?.role;
  const canTriage = Boolean(role && hasMinRole(role, "editor"));
  const inboxCount = useInboxCount(slug, canTriage);
  const inboxTotal = inboxCount.data?.total;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center px-4">
        <Link
          href="/projects"
          onClick={onNavigate}
          className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="ORBIT — accueil"
        >
          <OrbitLogo />
        </Link>
      </div>

      <div className="px-3 pb-3">
        <ProjectSwitcher slug={slug} />
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4" aria-label="Navigation principale">
        {slug ? (
          <>
            <p className="px-2.5 pb-1.5 pt-2 text-[10.5px] font-semibold uppercase tracking-[0.09em] text-sidebar-muted">
              Projet
            </p>
            <ul className="grid gap-0.5">
              {PROJECT_NAV.filter(
                (item) => item.segment !== "settings" && (!item.minRole || !role || hasMinRole(role, item.minRole)),
              ).map((item) => (
                <li key={item.segment || "overview"}>
                  <NavLink
                    href={projectHref(slug, item.segment)}
                    active={active?.segment === item.segment}
                    icon={item.icon}
                    label={item.label}
                    onNavigate={onNavigate}
                    badge={item.segment === "inbox" ? inboxTotal : undefined}
                    badgeLabel={
                      item.segment === "inbox" && inboxCount.data
                        ? `${inboxCount.data.proposals} proposition(s), ${inboxCount.data.conflicts} contradiction(s)`
                        : undefined
                    }
                  />
                </li>
              ))}
            </ul>
            <p className="px-2.5 pb-1.5 pt-5 text-[10.5px] font-semibold uppercase tracking-[0.09em] text-sidebar-muted">
              Administration
            </p>
            <ul className="grid gap-0.5">
              {PROJECT_NAV.filter((item) => item.segment === "settings").map((item) =>
                !item.minRole || hasMinRole(role, item.minRole) ? (
                  <li key={item.segment}>
                    <NavLink
                      href={projectHref(slug, item.segment)}
                      active={active?.segment === item.segment}
                      icon={item.icon}
                      label={item.label}
                      onNavigate={onNavigate}
                    />
                  </li>
                ) : null,
              )}
            </ul>
          </>
        ) : (
          <>
            <ul className="grid gap-0.5 pt-1">
              <li>
                <NavLink
                  href="/projects"
                  active={pathname === "/projects"}
                  icon={LayoutGrid}
                  label="Projets"
                  onNavigate={onNavigate}
                />
              </li>
            </ul>
            <div className="mt-4 rounded-lg border border-dashed border-sidebar-border p-3 text-xs leading-relaxed text-sidebar-muted">
              Sélectionnez un projet pour accéder à ses sources, sa mémoire, l&apos;explorateur de contexte et
              l&apos;observabilité.
            </div>
          </>
        )}
      </nav>

      <div className="grid shrink-0 gap-2.5 border-t border-sidebar-border px-4 py-3">
        <SystemStatus />
        <div className="flex items-center gap-2 text-[10.5px] text-sidebar-muted">
          <ConstellationDots />
          <span>Programme NOVA · Devoteam</span>
        </div>
      </div>
    </div>
  );
}

/** Fixed desktop sidebar (≥ lg). */
export function AppSidebar({ slug }: { slug?: string }) {
  return (
    <aside className="sticky top-0 hidden h-dvh w-[248px] shrink-0 border-r border-sidebar-border bg-sidebar lg:block">
      <SidebarContent slug={slug} />
    </aside>
  );
}
