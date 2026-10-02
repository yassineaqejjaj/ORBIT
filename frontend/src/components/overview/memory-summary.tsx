"use client";

import Link from "next/link";
import { ArrowRight, Brain } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Overview } from "@/lib/api/types";
import { MEMORY_SCOPE_META, MEMORY_SCOPES, MEMORY_STATUS_META, type MemoryStatus } from "@/lib/enums";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Statuses other than "proposed": the number to validate is already shown by the flow and the attention list. */
const SETTLED_STATUSES: { status: MemoryStatus; swatch: string }[] = [
  { status: "validated", swatch: "bg-brand" },
  { status: "superseded", swatch: "bg-brand/45" },
  { status: "obsolete", swatch: "bg-muted-foreground/40" },
  { status: "forgotten", swatch: "bg-muted-foreground/20" },
];

/** Level 2 — what ORBIT has memorised: lifecycle of settled items and scope distribution. */
export function MemorySummary({ slug, overview, className }: { slug: string; overview: Overview; className?: string }) {
  const byStatus = overview.memory_by_status;
  const byScope = overview.memory_by_scope;
  const total = overview.stats.memory_items;
  const proposed = byStatus.proposed ?? 0;
  const settled = SETTLED_STATUSES.map((entry) => ({ ...entry, count: byStatus[entry.status] ?? 0 }));
  const settledTotal = settled.reduce((sum, entry) => sum + entry.count, 0);
  const scopes = MEMORY_SCOPES.map((scope) => ({ scope, count: byScope[scope] ?? 0 })).filter((entry) => entry.count > 0);

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Brain className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Mémoire</CardTitle>
      </CardHeader>
      <CardContent className="grid flex-1 content-start gap-4">
        <p className="text-[13px] text-muted-foreground">
          <span className="text-lg font-semibold tabular-nums text-foreground">{formatNumber(total, 0)}</span> éléments, dont{" "}
          {formatNumber(settledTotal, 0)} traités par la revue ou le cycle de vie
        </p>

        {settledTotal > 0 ? (
          <div className="grid gap-2">
            <div className="flex h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label="Répartition des éléments traités par statut">
              {settled
                .filter((entry) => entry.count > 0)
                .map((entry) => (
                  <span key={entry.status} className={cn("h-full", entry.swatch)} style={{ width: `${(entry.count / settledTotal) * 100}%` }} />
                ))}
            </div>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {settled.map((entry) => (
                <li key={entry.status} className="inline-flex items-center gap-1.5">
                  <span className={cn("size-2 rounded-sm", entry.swatch)} aria-hidden />
                  <span className="font-semibold tabular-nums text-foreground">{formatNumber(entry.count, 0)}</span>
                  {MEMORY_STATUS_META[entry.status].label.toLowerCase()}
                  {entry.count > 1 ? "s" : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {scopes.length > 0 ? (
          <div className="grid gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">Portée</p>
            <ul className="flex flex-wrap gap-1.5">
              {scopes.map((entry) => (
                <li
                  key={entry.scope}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-foreground"
                >
                  <span className="font-semibold tabular-nums">{formatNumber(entry.count, 0)}</span>
                  {MEMORY_SCOPE_META[entry.scope].label.toLowerCase()}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border px-5 py-3">
        <Link
          href={projectHref(slug, "memory")}
          className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Voir la mémoire
          <ArrowRight className="size-3" aria-hidden />
        </Link>
        {proposed > 0 ? (
          <Link
            href={projectHref(slug, "inbox")}
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Revoir les propositions
            <ArrowRight className="size-3" aria-hidden />
          </Link>
        ) : null}
      </div>
    </Card>
  );
}
