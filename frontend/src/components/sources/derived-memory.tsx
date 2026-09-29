"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, Brain } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { ScopeBadge } from "@/components/domain/scope-badge";
import { ScoreBar } from "@/components/domain/score-bar";
import { StatusBadge } from "@/components/domain/status-badge";
import { memoryItemHref } from "@/components/overview/latest-decisions-card";
import { EmptyState } from "@/components/ui/empty-state";
import type { MemoryItem } from "@/lib/api/types";
import { MEMORY_KIND_META, MEMORY_KINDS } from "@/lib/enums";
import { formatDate, plural, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

/** "Mémoire dérivée" tab: memory items extracted from this document, grouped by kind order. */
export function DerivedMemory({ slug, items }: { slug: string; items: readonly MemoryItem[] }) {
  const sorted = React.useMemo(
    () =>
      [...items].sort(
        (a, b) => MEMORY_KINDS.indexOf(a.kind) - MEMORY_KINDS.indexOf(b.kind) || b.confidence - a.confidence,
      ),
    [items],
  );
  const summary = React.useMemo(() => {
    const counts = new Map<string, number>();
    for (const i of items) counts.set(i.kind, (counts.get(i.kind) ?? 0) + 1);
    return MEMORY_KINDS.filter((k) => counts.has(k)).map((k) => plural(counts.get(k) ?? 0, MEMORY_KIND_META[k].label.toLowerCase()));
  }, [items]);

  if (sorted.length === 0) {
    return (
      <EmptyState
        icon={<Brain />}
        title="Aucune mémoire dérivée"
        description="Les décisions (« Décision : … »), besoins (« En tant que … je veux »), contraintes et risques détectés dans ce document deviennent des éléments de mémoire, avec leur provenance."
      />
    );
  }

  return (
    <div className="grid gap-3">
      <p className="text-xs text-muted-foreground">
        {plural(sorted.length, "élément extrait", "éléments extraits")} de ce document : {summary.join(", ")}.
      </p>
      <ul className="grid gap-2">
        {sorted.map((item) => (
          <li key={item.id}>
            <Link
              href={memoryItemHref(slug, item.id)}
              className={cn(
                "group grid gap-2 rounded-lg border border-border bg-card px-4 py-3 shadow-xs transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                (item.status === "superseded" || item.status === "obsolete" || item.status === "forgotten") && "opacity-75",
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <MemoryKindBadge kind={item.kind} />
                <StatusBadge kind="memory" status={item.status} />
                <ScopeBadge scope={item.scope} />
                {item.classification >= 2 ? <ClassificationBadge level={item.classification} showLabel={false} /> : null}
                <ArrowUpRight
                  className="ml-auto size-4 text-subtle-foreground transition-colors group-hover:text-primary"
                  aria-hidden
                />
              </div>
              <p className="text-[13px] font-medium leading-snug text-foreground group-hover:text-primary">{item.title}</p>
              {item.content ? (
                <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{truncate(item.content, 280)}</p>
              ) : null}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  Confiance <ScoreBar value={item.confidence} widthClassName="w-14" />
                </span>
                <span>Depuis le {formatDate(item.valid_from)}</span>
                {item.version > 1 ? <span>v{item.version}</span> : null}
                {item.created_by_label ? <span>par {item.created_by_label}</span> : null}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
