"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChanges } from "@/lib/api/features-feed";
import { formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Change-feed types grouped into the few lines a returning user cares about. */
const GROUPS: { label: (n: number) => string; types: string[] }[] = [
  { label: (n) => `élément${n > 1 ? "s" : ""} mémorisé${n > 1 ? "s" : ""}`, types: ["memory.created"] },
  { label: (n) => `validation${n > 1 ? "s" : ""} en mémoire`, types: ["memory.validated"] },
  { label: (n) => `élément${n > 1 ? "s" : ""} remplacé${n > 1 ? "s" : ""}`, types: ["memory.superseded"] },
  { label: (n) => `contradiction${n > 1 ? "s" : ""} détectée${n > 1 ? "s" : ""}`, types: ["memory.conflict_detected"] },
  {
    label: (n) => `mise${n > 1 ? "s" : ""} à jour de sources`,
    types: ["document.ingested", "document.new_version", "connector.synced"],
  },
  { label: (n) => `snapshot${n > 1 ? "s" : ""} enregistré${n > 1 ? "s" : ""}`, types: ["snapshot.created"] },
];

const STORAGE_PREFIX = "orbit:last-visit:";
const SESSION_PREFIX = "orbit:visit-baseline:";

/**
 * Previous visit of this project in this browser (per-viewer convenience, not shared state).
 * The baseline is frozen for the browser session so it does not move while the user navigates.
 */
function useVisitBaseline(slug: string): string | null {
  const [baseline, setBaseline] = React.useState<string | null>(null);
  React.useEffect(() => {
    try {
      const frozen = window.sessionStorage.getItem(SESSION_PREFIX + slug);
      if (frozen !== null) {
        setBaseline(frozen || null);
      } else {
        const previous = window.localStorage.getItem(STORAGE_PREFIX + slug);
        window.sessionStorage.setItem(SESSION_PREFIX + slug, previous ?? "");
        setBaseline(previous);
      }
      window.localStorage.setItem(STORAGE_PREFIX + slug, new Date().toISOString());
    } catch {
      setBaseline(null); // storage unavailable (private mode, blocked site data): feature simply hidden
    }
  }, [slug]);
  return baseline;
}

/** "Depuis votre dernière visite" — built on the real change feed; hidden on a first visit. */
export function SinceLastVisit({ slug, className }: { slug: string; className?: string }) {
  const since = useVisitBaseline(slug);
  const changes = useChanges(slug, { since: since ?? undefined, page_size: 100 }, Boolean(since));
  if (!since || changes.isPending || changes.isError) return null;

  const counts = GROUPS.map((group) => ({
    label: group.label,
    count: changes.data.items.filter((event) => group.types.includes(String(event.type))).length,
  })).filter((group) => group.count > 0);

  return (
    <Card className={cn(className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Sparkles className="size-4 text-brand" aria-hidden />
        <CardTitle>Depuis votre dernière visite</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2">
        <p className="text-xs text-muted-foreground">Le {formatDateTime(since)}</p>
        {counts.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Rien de nouveau dans le projet.</p>
        ) : (
          <ul className="grid gap-1 text-[13px] text-foreground">
            {counts.map((group) => (
              <li key={group.label(2)}>
                <span className="font-semibold tabular-nums">{formatNumber(group.count, 0)}</span> {group.label(group.count)}
              </li>
            ))}
          </ul>
        )}
        <Link
          href={projectHref(slug, "changes")}
          className="inline-flex w-fit items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Voir les changements
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </CardContent>
    </Card>
  );
}
