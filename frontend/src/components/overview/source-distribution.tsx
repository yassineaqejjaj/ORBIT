"use client";

import Link from "next/link";
import { ArrowRight, Database } from "lucide-react";

import { EnumIcon } from "@/components/domain/enum-icon";
import { projectHref } from "@/components/layout/nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SourceKind } from "@/lib/enums";
import { SOURCE_KIND_META, SOURCE_KINDS } from "@/lib/enums";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Level 3 — contents by source type, one ORBIT color + icons (no categorical rainbow). */
export function SourceDistribution({
  slug,
  byKind,
  className,
}: {
  slug: string;
  byKind: Partial<Record<SourceKind, number>>;
  className?: string;
}) {
  const rows = SOURCE_KINDS.map((kind) => ({ kind, count: byKind[kind] ?? 0 }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count);
  const max = Math.max(1, ...rows.map((row) => row.count));

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Database className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Sources</CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        {rows.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Aucun contenu ingéré pour l&apos;instant.</p>
        ) : (
          <ul className="grid gap-1" aria-label="Contenus par type de source">
            {rows.map((row) => {
              const meta = SOURCE_KIND_META[row.kind];
              return (
                <li key={row.kind}>
                  <Link
                    href={`${projectHref(slug, "sources")}?source_kind=${row.kind}`}
                    className="grid grid-cols-[minmax(0,9rem)_1fr_2rem] items-center gap-3 rounded-md px-1.5 py-1.5 text-[13px] transition-colors duration-150 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                  >
                    <span className="flex min-w-0 items-center gap-2 text-foreground">
                      <EnumIcon name={meta.icon} className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">{meta.label}</span>
                    </span>
                    <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                      <span className="block h-full rounded-full bg-brand/70" style={{ width: `${(row.count / max) * 100}%` }} />
                    </span>
                    <span className="text-right font-medium tabular-nums text-foreground">{formatNumber(row.count, 0)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
      <div className="border-t border-border px-5 py-3">
        <Link
          href={`${projectHref(slug, "sources")}?tab=sources`}
          className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Voir les sources
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </div>
    </Card>
  );
}
