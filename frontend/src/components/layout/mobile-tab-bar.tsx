"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { activeProjectNav, navItem, projectHref, type ProjectNavItem } from "@/components/layout/nav";
import { useInboxCount } from "@/lib/api/features-feed";
import { useProject } from "@/lib/api/hooks";
import { hasMinRole } from "@/lib/enums";
import { cn } from "@/lib/utils";

/** The five mobile entries (NOVA adaptation table); the header menu still opens the full drawer. */
const TAB_SEGMENTS: ReadonlyArray<{ segment: ProjectNavItem["segment"]; short?: string }> = [
  { segment: "", short: "Vue d’ensemble" },
  { segment: "sources" },
  { segment: "memory" },
  { segment: "explorer" },
  { segment: "inbox", short: "Revue" },
];

/** Fixed bottom tab bar below lg, for project pages. */
export function MobileTabBar({ slug }: { slug?: string }) {
  const pathname = usePathname();
  const project = useProject(slug);
  const role = project.data?.role;
  const canTriage = Boolean(role && hasMinRole(role, "editor"));
  const inboxCount = useInboxCount(slug, canTriage);
  if (!slug) return null;
  const active = activeProjectNav(pathname, slug);

  const tabs = TAB_SEGMENTS.filter(({ segment }) => {
    const item = navItem(segment);
    return !item.minRole || !role || hasMinRole(role, item.minRole);
  });

  return (
    <nav
      aria-label="Navigation rapide"
      className="pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface/95 backdrop-blur-md lg:hidden"
    >
      <ul className="mx-auto flex h-16 max-w-xl items-stretch">
        {tabs.map(({ segment, short }) => {
          const item = navItem(segment);
          const Icon = item.icon;
          const isActive = active?.segment === segment;
          const count = segment === "inbox" ? inboxCount.data?.total : undefined;
          return (
            <li key={segment || "overview"} className="min-w-0 flex-1">
              <Link
                href={projectHref(slug, segment)}
                aria-current={isActive ? "page" : undefined}
                aria-label={count ? `${item.label} (${count} à revoir)` : item.label}
                className={cn(
                  "flex h-full flex-col items-center justify-center gap-1 px-1 text-[10.5px] font-medium leading-none transition-colors duration-150",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50",
                  isActive ? "text-accent-text" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="relative">
                  <Icon className="size-5" aria-hidden />
                  {count ? (
                    <span
                      className="absolute -right-2.5 -top-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9.5px] font-semibold tabular-nums text-primary-foreground"
                      aria-hidden
                    >
                      {count > 99 ? "99+" : count}
                    </span>
                  ) : null}
                </span>
                <span className="max-w-full truncate">{short ?? item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
