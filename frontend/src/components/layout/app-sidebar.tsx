"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, LayoutGrid, PanelLeftClose, PanelLeftOpen, Sparkles } from "lucide-react";

import { OrbitLogo, OrbitMark } from "@/components/brand/orbit-logo";
import {
  activeProjectNav,
  navItem,
  PROJECT_NAV_SECTIONS,
  projectHref,
  type ProjectNavItem,
} from "@/components/layout/nav";
import { PresencePill, usePresence } from "@/components/layout/presence-pill";
import { ProjectSwitcher } from "@/components/layout/project-switcher";
import { useShell } from "@/components/layout/shell-context";
import { UserMenu } from "@/components/layout/user-menu";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useInboxCount } from "@/lib/api/features-feed";
import { useMeta, useProject } from "@/lib/api/hooks";
import { hasMinRole, ROLE_META } from "@/lib/enums";
import { plural } from "@/lib/format";
import { cn, modKeyLabel } from "@/lib/utils";

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
  collapsed,
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
  /** Icon only, label in a right-side tooltip (kept for screen readers). */
  collapsed?: boolean;
}) {
  const count = badge ? (badge > 99 ? "99+" : String(badge)) : null;
  const link = (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex items-center rounded-lg text-[14px] transition-colors duration-150 motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        touch ? "h-11" : "h-9",
        collapsed ? "mx-auto w-10 justify-center" : "gap-2.5 px-2.5",
        active
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : "text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
      )}
    >
      <Icon
        className={cn(
          "size-[18px] shrink-0",
          active ? "text-brand" : "text-sidebar-muted group-hover:text-sidebar-foreground",
        )}
        aria-hidden
      />
      <span className={collapsed ? "sr-only" : "truncate"}>{label}</span>
      {count ? (
        collapsed ? (
          <span
            className="absolute right-0.5 top-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9.5px] font-semibold tabular-nums text-primary-foreground"
            aria-hidden
          >
            {count}
          </span>
        ) : (
          <span
            className="ml-auto inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1.5 text-[10.5px] font-semibold tabular-nums text-primary-foreground"
            aria-hidden
          >
            {count}
          </span>
        )
      ) : null}
      {count && badgeLabel ? <span className="sr-only">{`(${badgeLabel})`}</span> : null}
    </Link>
  );
  if (!collapsed) return link;
  return (
    <SimpleTooltip content={count ? `${label} · ${count}` : label} side="right">
      {link}
    </SimpleTooltip>
  );
}

/** Primary action under the project switcher: ask a question about the project's memory. */
function AskOrbitButton({
  slug,
  active,
  onNavigate,
  collapsed,
}: {
  slug: string;
  active: boolean;
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const link = (
    <Link
      href={projectHref(slug, "ask")}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? "Demander à ORBIT" : undefined}
      className={cn(
        "flex h-9 items-center gap-2 rounded-lg border text-[14px] font-medium transition-colors duration-150 motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        collapsed ? "mx-auto w-10 justify-center" : "px-2.5",
        active
          ? "border-accent-coral/35 bg-accent-soft text-accent-text"
          : "border-accent-coral/20 bg-accent-soft/70 text-accent-text hover:border-accent-coral/35 hover:bg-accent-soft",
      )}
    >
      <Sparkles className="size-4 shrink-0" aria-hidden />
      {collapsed ? null : "Demander à ORBIT"}
    </Link>
  );
  return collapsed ? (
    <SimpleTooltip content="Demander à ORBIT" side="right">
      {link}
    </SimpleTooltip>
  ) : (
    link
  );
}

/** Footer line: version and backend details in a tooltip. */
function VersionLine() {
  const meta = useMeta();
  if (!meta.isSuccess) return null;
  const detail = `Version ${meta.data.version} · ${meta.data.embedding_model} · reranker ${meta.data.reranker}${meta.data.llm ? ` · LLM ${meta.data.llm}` : " · mode déterministe"}`;
  const shortVersion = meta.data.version.split(".").slice(0, 2).join(".");
  return (
    <SimpleTooltip content={detail} side="top" align="start">
      <p className="w-fit rounded px-2 text-[10.5px] text-sidebar-muted" tabIndex={0}>
        Devoteam · v{shortVersion}
      </p>
    </SimpleTooltip>
  );
}

function SectionTitle({ children, collapsed }: { children: React.ReactNode; collapsed?: boolean }) {
  if (collapsed) {
    return (
      <>
        <p className="sr-only">{children}</p>
        <div className="mx-4 my-2 h-px bg-sidebar-border" aria-hidden />
      </>
    );
  }
  return <p className="group-label px-2.5 pb-1.5 pt-5">{children}</p>;
}

export interface SidebarContentProps {
  slug?: string;
  /** Called after a navigation (closes the mobile sheet). */
  onNavigate?: () => void;
  /** Mobile drawer: collapsible sections and 44 px touch targets. */
  collapsible?: boolean;
  /** Desktop sidebar collapsed to 64 px (icons only). */
  collapsed?: boolean;
  /** Collapse / expand control (desktop sidebar only). */
  onToggleCollapsed?: () => void;
}

/** Sidebar body (used by the desktop aside and the mobile sheet). */
export function SidebarContent({ slug, onNavigate, collapsible = false, collapsed = false, onToggleCollapsed }: SidebarContentProps) {
  const pathname = usePathname();
  const project = useProject(slug);
  const active = slug ? activeProjectNav(pathname, slug) : undefined;
  const role = project.data?.role;
  const canTriage = Boolean(role && hasMinRole(role, "editor"));
  const inboxCount = useInboxCount(slug, canTriage);
  const inboxTotal = inboxCount.data?.total;
  const presence = usePresence(slug, inboxTotal);
  const [mod, setMod] = React.useState("⌘");
  React.useEffect(() => setMod(modKeyLabel()), []);

  const visible = (segment: ProjectNavItem["segment"]) => {
    const item = navItem(segment);
    return !item.minRole || !role || hasMinRole(role, item.minRole);
  };
  const sections = PROJECT_NAV_SECTIONS.map((section) => ({
    ...section,
    segments: section.segments.filter(visible),
  })).filter((section) => section.segments.length > 0);
  // Settings live in the footer, next to the account menu (NOVA layout).
  const settingsVisible = Boolean(slug) && visible("settings");
  const navSections = sections
    .map((section) => ({ ...section, segments: section.segments.filter((segment) => segment !== "settings") }))
    .filter((section) => section.segments.length > 0);

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
          collapsed={collapsed}
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

  const toggleLabel = `${collapsed ? "Déplier" : "Replier"} la barre latérale (${mod === "⌘" ? "⌘" : `${mod}+`}\\)`;
  const toggleButton = onToggleCollapsed ? (
    <SimpleTooltip content={toggleLabel} side={collapsed ? "right" : "bottom"}>
      <button
        type="button"
        onClick={onToggleCollapsed}
        aria-label={toggleLabel}
        aria-expanded={!collapsed}
        aria-keyshortcuts="Meta+Backslash Control+Backslash"
        className="flex size-8 items-center justify-center rounded-lg text-sidebar-muted transition-colors duration-150 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        {collapsed ? <PanelLeftOpen className="size-4" aria-hidden /> : <PanelLeftClose className="size-4" aria-hidden />}
      </button>
    </SimpleTooltip>
  ) : null;

  return (
    <div className="flex h-full flex-col">
      {collapsed ? (
        <div className="flex shrink-0 flex-col items-center gap-2 pb-2 pt-4">
          <Link
            href="/projects"
            onClick={onNavigate}
            className="rounded-lg p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            aria-label="ORBIT — accueil"
          >
            <OrbitMark className="size-7" />
          </Link>
          {toggleButton}
        </div>
      ) : (
        <div className="flex h-16 shrink-0 items-center justify-between gap-2 pl-4 pr-3">
          <Link
            href="/projects"
            onClick={onNavigate}
            className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            aria-label="ORBIT — accueil"
          >
            <OrbitLogo size={22} />
          </Link>
          {toggleButton}
        </div>
      )}

      <div className={cn("grid gap-2 pb-2", collapsed ? "justify-items-center px-2" : "px-3")}>
        <PresencePill presence={presence} collapsed={collapsed} onNavigate={onNavigate} />
        <ProjectSwitcher slug={slug} compact={collapsed} />
        {slug ? (
          <AskOrbitButton slug={slug} active={active?.segment === "ask"} onNavigate={onNavigate} collapsed={collapsed} />
        ) : null}
      </div>

      <nav className={cn("flex-1 overflow-y-auto pb-4", collapsed ? "px-2" : "px-3")} aria-label="Navigation principale">
        {slug ? (
          navSections.map((section) => {
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
                  <SectionTitle collapsed={collapsed}>{section.label}</SectionTitle>
                  <ul className="grid gap-0.5">{section.segments.map(renderItem)}</ul>
                </div>
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
                  className="flex h-11 w-full items-center gap-2 rounded-lg px-2.5 text-left text-[14px] font-medium text-sidebar-foreground transition-colors duration-150 hover:bg-sidebar-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 motion-reduce:transition-none"
                >
                  <span className="flex-1">{section.label}</span>
                  {!open && hasBadge ? (
                    <span className="size-1.5 rounded-full bg-accent-coral" aria-label="Éléments à traiter" />
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
                  collapsed={collapsed}
                />
              </li>
            </ul>
            {collapsed ? null : (
              <div className="mt-4 rounded-xl border border-dashed border-sidebar-border p-3 text-xs leading-relaxed text-sidebar-muted">
                Sélectionnez un projet pour accéder à ses sources, sa mémoire, ses contextes et son suivi.
              </div>
            )}
          </>
        )}
      </nav>

      <div className={cn("grid shrink-0 gap-1 border-t border-sidebar-border py-2", collapsed ? "px-2" : "px-3")}>
        {settingsVisible ? <ul className="grid">{renderItem("settings")}</ul> : null}
        <UserMenu
          variant="sidebar"
          collapsed={collapsed}
          roleLabel={role ? ROLE_META[role].label : undefined}
        />
        {collapsed ? null : <VersionLine />}
      </div>
    </div>
  );
}

/** Sticky desktop sidebar (≥ lg): 224 px expanded, 64 px collapsed (⌘\\, remembered). */
export function AppSidebar({ slug }: { slug?: string }) {
  const { sidebarCollapsed, toggleSidebar } = useShell();
  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-out motion-reduce:transition-none lg:block",
        sidebarCollapsed ? "w-16" : "w-56",
      )}
      data-collapsed={sidebarCollapsed || undefined}
    >
      <SidebarContent slug={slug} collapsed={sidebarCollapsed} onToggleCollapsed={toggleSidebar} />
    </aside>
  );
}
