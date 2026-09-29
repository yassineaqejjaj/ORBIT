"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Gavel, Link2 } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScopeBadge } from "@/components/domain/scope-badge";
import { projectHref } from "@/components/layout/nav";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import type { MemoryItem } from "@/lib/api/types";
import { formatDate, formatPercent, plural, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

export function memoryItemHref(slug: string, id: string): string {
  return `${projectHref(slug, "memory")}?item=${encodeURIComponent(id)}`;
}

export function LatestDecisionsCard({
  slug,
  decisions,
  className,
}: {
  slug: string;
  decisions: readonly MemoryItem[];
  className?: string;
}) {
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Gavel className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Décisions en vigueur</CardTitle>
        <CardAction>
          <Link
            href={`${projectHref(slug, "memory")}?kind=decision&status=validated`}
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Toutes les décisions
            <ArrowRight className="size-3" aria-hidden />
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent className="flex-1">
        {decisions.length === 0 ? (
          <EmptyState
            size="sm"
            variant="plain"
            icon={<Gavel />}
            title="Aucune décision validée"
            description="Les décisions extraites des comptes rendus apparaissent ici une fois validées."
            action={
              <Link
                href={`${projectHref(slug, "memory")}?status=proposed`}
                className="text-[13px] font-medium text-primary hover:underline"
              >
                Revoir les propositions
              </Link>
            }
          />
        ) : (
          <ul className="grid gap-2">
            {decisions.map((d) => (
              <li key={d.id}>
                <Link
                  href={memoryItemHref(slug, d.id)}
                  className="group grid gap-1.5 rounded-lg border border-border bg-background px-3.5 py-3 transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded bg-teal-50 text-teal-700 ring-1 ring-inset ring-teal-600/20 dark:bg-teal-400/10 dark:text-teal-300 dark:ring-teal-400/25">
                      <Gavel className="size-3" aria-hidden />
                    </span>
                    <p className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-foreground group-hover:text-primary">
                      {d.title}
                    </p>
                    {d.classification >= 2 ? <ClassificationBadge level={d.classification} showLabel={false} /> : null}
                  </div>
                  {d.content ? (
                    <p className="line-clamp-2 pl-7 text-xs leading-relaxed text-muted-foreground">{truncate(d.content, 220)}</p>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-7 text-[11.5px] text-muted-foreground">
                    <ScopeBadge scope={d.scope} />
                    <span title="Date d'entrée en vigueur">En vigueur depuis le {formatDate(d.valid_from)}</span>
                    <span className="inline-flex items-center gap-1">
                      <Link2 className="size-3" aria-hidden />
                      {plural(d.provenance_count, "source")}
                    </span>
                    <span title="Confiance">Confiance {formatPercent(d.confidence)}</span>
                    <RelativeTime date={d.updated_at} className="ml-auto" />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
