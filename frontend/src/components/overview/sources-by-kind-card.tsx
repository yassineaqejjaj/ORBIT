"use client";

import * as React from "react";
import Link from "next/link";
import { Database } from "lucide-react";

import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { projectHref } from "@/components/layout/nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SOURCE_KIND_META, SOURCE_KINDS, type SourceKind } from "@/lib/enums";
import { formatNumber, formatPercent } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

/** Documents per source kind — a ranked bar list (identity carried by icon + label, magnitude by bar length). */
export function SourcesByKindCard({
  slug,
  byKind,
  className,
}: {
  slug: string;
  byKind: Partial<Record<SourceKind, number>>;
  className?: string;
}) {
  const rows = React.useMemo(
    () =>
      SOURCE_KINDS.map((kind) => ({ kind, value: byKind[kind] ?? 0 }))
        .filter((r) => r.value > 0)
        .sort((a, b) => b.value - a.value),
    [byKind],
  );
  const max = rows.reduce((m, r) => Math.max(m, r.value), 0);
  const total = rows.reduce((acc, r) => acc + r.value, 0);

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Database className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Contenus par type de source</CardTitle>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">{formatNumber(total, 0)} au total</span>
      </CardHeader>
      <CardContent className="flex-1">
        {rows.length === 0 ? (
          <EmptyState
            size="sm"
            variant="plain"
            icon={<Database />}
            title="Aucun contenu ingéré"
            description="Téléversez des documents ou importez des tickets, fiches CRM et retours utilisateurs."
          />
        ) : (
          <ul className="grid gap-1">
            {rows.map((row) => {
              const meta = SOURCE_KIND_META[row.kind];
              const t = toneClasses(meta.tone);
              return (
                <li key={row.kind}>
                  <Link
                    href={`${projectHref(slug, "sources")}?kind=${row.kind}`}
                    className="group grid grid-cols-[minmax(0,9.5rem)_1fr_auto] items-center gap-3 rounded-md px-1.5 py-1.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    title={`${meta.label} : ${formatNumber(row.value, 0)} (${formatPercent(total ? row.value / total : 0)})`}
                  >
                    <SourceKindIcon kind={row.kind} withLabel size="sm" className="text-foreground" />
                    <span className={cn("relative h-2 overflow-hidden rounded-full", t.track)} aria-hidden>
                      <span
                        className={cn("absolute inset-y-0 left-0 rounded-full", t.bar)}
                        style={{ width: `${max ? Math.max(4, (row.value / max) * 100) : 0}%` }}
                      />
                    </span>
                    <span className="w-10 text-right text-[13px] font-medium tabular-nums text-foreground">
                      {formatNumber(row.value, 0)}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
