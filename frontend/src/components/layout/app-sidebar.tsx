"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, LayoutGrid, Sparkles } from "lucide-react";

import { OrbitLogo } from "@/components/brand/orbit-logo";
import {
  activeProjectNav,
  navItem,
  PROJECT_NAV_SECTIONS,
  projectHref,
  type ProjectNavItem,
} from "@/components/layout/nav";
import { ProjectSwitcher } from "@/components/layout/project-switcher";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useInboxCount } from "@/lib/api/features-feed";
import { useMeta, useProject } from "@/lib/api/hooks";
import { hasMinRole } from "@/lib/enums";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

type NavIcon = React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

function NavLink({
  href,
  active,
  icon: Icon,
  label,
  onNavigate,
  badge,
  badgeLabel,
  touch,
}: {
  href: string;
  active: boolean;
  icon: NavIcon;
  label: string;
  onNavigate?: () => void;
  /** Actionable counter (items waiting for someone); hidden when 0 or undefined. */
  badge?: number;
  badgeLabel?: string;
  /** Larger touch targets (mobile drawer). */
  touch?: boolean;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group flex items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors duration-150 motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        touch ? "h-11" : "h-8",
        active
          ? "bg-sidebar-accent font-semibold text-sidebar-accent-foreground"
          : "font-medium text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
      )}
    >
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

/** Primary action under the project switcher: ask a question about the project's memory. */
function AskOrbitButton({ slug, active, onNavigate }: { slug: string; active: boolean; onNavigate?: () => void }) {
  return (
    <Link
      href={projectHref(slug, "ask")}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-9 items-center gap-2 rounded-md border px-2.5 text-[13px] font-semibold transition-colors duration-150 motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-brand/40 bg-brand-soft text-brand"
          : "border-brand/25 bg-brand-soft/60 text-brand hover:border-brand/40 hover:bg-brand-soft",
      )}
    >
      <Sparkles className="size-4 shrink-0" aria-hidden />
      Demander à ORBIT
    </Link>
  );
}

function SystemStatus() {
  const meta = useMeta();
  const ok = meta.isSuccess;
  const label = meta.isPending ? "Connexion…" : ok ? "Opérationnel" : "API injoignable";
  const detail = ok
    ? `Version ${meta.data.version} · ${meta.data.embedding_model} · reranker ${meta.data.reranker}${meta.data.llm ? ` · LLM ${meta.data.llm}` : " · mode déterministe"}`
    : meta.isError
      ? "Le backend ORBIT ne répond pas."
      : undefined;
  const shortVersion = ok ? meta.data.version.split(".").slice(0, 2).join(".") : null;
  return (
    <div className="grid gap-1">
      <SimpleTooltip content={detail} side="top" align="start">
        <div className="flex w-fit items-center gap-2 rounded text-[11.5px] text-sidebar-foreground" tabIndex={detail ? 0 : -1}>
          <span
            className={cn(
              "inline-flex size-2 rounded-full",
              meta.isPending ? "bg-slate-400" : ok ? "bg-emerald-500" : "bg-red-500",
            )}
            aria-hidden
          />
          <span>{label}</span>
        </div>
      </SimpleTooltip>
      <p className="text-[10.5px] text-sidebar-muted">
        Devoteam{shortVersion ? ` · v${shortVersion}` : ""}
      </p>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pb-1 pt-4 text-[10px] font-medium uppercase tracking-[0.1em] text-sidebar-muted/80">{children}</p>
  );
}

export interface SidebarContentProps {
  slug?: string;
  /** Called after a navigation (closes the mobile sheet). */
  onNavigate?: () => void;
  /** Mobile drawer: collapsible sections and 44 px touch targets. */
  collapsible?: boolean;
}

/** Sidebar body (used by the desktop aside and the mobile sheet). */
export function SidebarContent({ slug, onNavigate, collapsible = false }: SidebarContentProps) {
  const pathname = usePathname();
  const project = useProject(slug);
  const active = slug ? activeProjectNav(pathname, slug) : undefined;
  const role = project.data?.role;
  const canTriage = Boolean(role && hasMinRole(role, "editor"));
  const inboxCount = useInboxCount(slug, canTriage);
  const inboxTotal = inboxCount.data?.total;

  const visible = (segment: ProjectNavItem["segment"]) => {
    const item = navItem(segment);
    return !item.minRole || !role || hasMinRole(role, item.minRole);
  };
  const sections = PROJECT_NAV_SECTIONS.map((section) => ({
    ...section,
    segments: section.segments.filter(visible),
  })).filter((section) => section.segments.length > 0);

  // Mobile: the section holding the current page starts open (and stays open when the drawer is reopened).
  const activeSection = sections.find((section) => active && section.segments.includes(active.segment))?.label ?? null;
  const [openSections, setOpenSections] = React.useState<Set<string>>(
    () => new Set(activeSection ? [activeSection] : []),
  );
  React.useEffect(() => {
    if (activeSection) setOpenSections((prev) => (prev.has(activeSection) ? prev : new Set(prev).add(activeSection)));
  }, [activeSection]);
  const toggle = (label: string) =>
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });

  const renderItem = (segment: ProjectNavItem["segment"]) => {
    if (!slug) return null;
    const item = navItem(segment);
    const isInbox = segment === "inbox";
    return (
      <li key={segment || "overview"}>
        <NavLink
          href={projectHref(slug, segment)}
          active={active?.segment === segment}
          icon={item.icon}
          label={item.label}
          onNavigate={onNavigate}
          touch={collapsible}
          badge={isInbox ? inboxTotal : undefined}
          badgeLabel={
            isInbox && inboxCount.data
              ? `${plural(inboxCount.data.proposals, "proposition")} à valider, ${plural(inboxCount.data.conflicts, "contradiction")} à arbitrer`
              : undefined
          }
        />
      </li>
    );
  };

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

      <div className="grid gap-2 px-3 pb-2">
        <ProjectSwitcher slug={slug} />
        {slug ? <AskOrbitButton slug={slug} active={active?.segment === "ask"} onNavigate={onNavigate} /> : null}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4" aria-label="Navigation principale">
        {slug ? (
          sections.map((section) => {
            if (!section.label) {
              return (
                <ul key="top" className="grid gap-0.5 pt-2">
                  {section.segments.map(renderItem)}
                </ul>
              );
            }
            if (!collapsible) {
              return (
                <div key={section.label}>
                  <SectionTitle>{section.label}</SectionTitle>
                  <ul className="grid gap-0.5">{section.segments.map(renderItem)}</ul>
                </div>
              );
            }
            if (section.label === "Administration") {
              // Mobile: a single settings entry needs no accordion.
              return (
                <ul key={section.label} className="grid gap-0.5 border-t border-sidebar-border pt-2 mt-2">
                  {section.segments.map(renderItem)}
                </ul>
              );
            }
            const open = openSections.has(section.label);
            const panelId = `nav-section-${section.label}`;
            const hasBadge = section.segments.includes("inbox") && Boolean(inboxTotal);
            return (
              <div key={section.label} className="pt-1">
                <button
                  type="button"
                  onClick={() => toggle(section.label as string)}
                  aria-expanded={open}
                  aria-controls={panelId}
                  className="flex h-11 w-full items-center gap-2 rounded-md px-2.5 text-left text-[13px] font-medium text-sidebar-foreground transition-colors duration-150 hover:bg-sidebar-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                >
                  <span className="flex-1">{section.label}</span>
                  {!open && hasBadge ? (
                    <span className="size-1.5 rounded-full bg-brand" aria-label="Éléments à traiter" />
                  ) : null}
                  <ChevronDown
                    className={cn(
                      "size-4 text-sidebar-muted transition-transform duration-150 motion-reduce:transition-none",
                      open ? "rotate-180" : "",
                    )}
                    aria-hidden
                  />
                </button>
                <ul id={panelId} hidden={!open} className="grid gap-0.5 pl-2">
                  {section.segments.map(renderItem)}
                </ul>
              </div>
            );
          })
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
                  touch={collapsible}
                />
              </li>
            </ul>
            <div className="mt-4 rounded-lg border border-dashed border-sidebar-border p-3 text-xs leading-relaxed text-sidebar-muted">
              Sélectionnez un projet pour accéder à ses sources, sa mémoire, ses contextes et son suivi.
            </div>
          </>
        )}
      </nav>

      <div className="shrink-0 px-4 py-3">
        <SystemStatus />
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
