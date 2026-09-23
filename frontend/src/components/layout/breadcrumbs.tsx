"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";

import { activeProjectNav, projectHref } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { useProject } from "@/lib/api/hooks";
import { shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Crumb {
  label: string;
  href?: string;
}

function safeDecode(v: string): string {
  try {
    return decodeURIComponent(v);
  } catch {
    return v;
  }
}

/** Header breadcrumb derived from the route: Projets / {projet} / {section} / {élément}. */
export function Breadcrumbs({ className }: { className?: string }) {
  const pathname = usePathname();
  const params = useParams<{ slug?: string; documentId?: string; name?: string }>();
  const { crumbLabels } = useShell();
  const slug = typeof params.slug === "string" ? params.slug : undefined;
  const project = useProject(slug);

  const crumbs: Crumb[] = [{ label: "Projets", href: "/projects" }];
  if (slug) {
    crumbs.push({ label: project.data?.name ?? safeDecode(slug), href: projectHref(slug) });
    const section = activeProjectNav(pathname, slug);
    if (section && section.segment) {
      crumbs.push({ label: section.label, href: projectHref(slug, section.segment) });
      const leaf = typeof params.documentId === "string" ? params.documentId : typeof params.name === "string" ? params.name : undefined;
      if (leaf) {
        const decoded = safeDecode(leaf);
        const fallback = params.documentId ? `Document ${shortId(decoded)}` : decoded;
        crumbs.push({ label: crumbLabels[decoded] ?? crumbLabels[leaf] ?? fallback });
      }
    }
  }

  return (
    <nav aria-label="Fil d'Ariane" className={cn("min-w-0", className)}>
      <ol className="flex min-w-0 items-center gap-1 text-[13px]">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li
              key={`${c.label}-${i}`}
              className={cn(
                "flex min-w-0 items-center gap-1",
                !last && "hidden sm:flex",
                !last && i < crumbs.length - 2 && "sm:hidden md:flex",
              )}
            >
              {c.href && !last ? (
                <Link
                  href={c.href}
                  className="truncate rounded px-1 py-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {c.label}
                </Link>
              ) : (
                <span className="truncate px-1 font-medium text-foreground" aria-current={last ? "page" : undefined}>
                  {c.label}
                </span>
              )}
              {!last ? <ChevronRight className="size-3.5 shrink-0 text-subtle-foreground" aria-hidden /> : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
