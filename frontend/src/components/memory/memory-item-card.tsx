"use client";

import * as React from "react";
import { CornerDownRight, GitBranch, History, Link2, Swords } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScopeBadge } from "@/components/domain/scope-badge";
import { ScoreBar } from "@/components/domain/score-bar";
import { StatusBadge } from "@/components/domain/status-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { MemoryItem } from "@/lib/api/types";
import { plural, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { isInactive } from "./memory-utils";

/** Plain-text preview of Markdown content (headings, emphasis, links and code markers removed). */
export function plainPreview(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/[*_`~]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export interface MemoryItemCardProps {
  item: MemoryItem;
  selected: boolean;
  onSelect: (id: string) => void;
  /** Involved in an unresolved `contradicts` relation. */
  conflict?: boolean;
  /** Title of the superseding item, when known. */
  supersededByTitle?: string | null;
}

/** Memory list entry: kind, scope, classification, status, confidence, provenance and lifecycle cues. */
export const MemoryItemCard = React.memo(function MemoryItemCard({
  item,
  selected,
  onSelect,
  conflict = false,
  supersededByTitle,
}: MemoryItemCardProps) {
  const inactive = isInactive(item);
  const superseded = item.status === "superseded";
  const forgotten = item.status === "forgotten";
  const preview = forgotten ? "Contenu effacé par oubli sélectif." : plainPreview(item.content);

  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      aria-current={selected ? "true" : undefined}
      data-memory-id={item.id}
      className={cn(
        "group relative grid w-full gap-2 rounded-xl border bg-card p-3.5 text-left shadow-xs transition-[border-color,box-shadow,background-color]",
        "hover:border-border-strong hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-brand/60 bg-brand-soft/40 ring-1 ring-brand/30 dark:bg-brand-soft/30" : "border-border",
        conflict && !selected && "border-l-[3px] border-l-amber-500 dark:border-l-amber-400",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <MemoryKindBadge kind={item.kind} />
          <ScopeBadge scope={item.scope} />
          {item.classification >= 1 ? <ClassificationBadge level={item.classification} showLabel={false} noTooltip /> : null}
          {!item.is_current ? (
            <Badge tone="neutral" variant="outline" icon={<History aria-hidden />}>
              Version antérieure
            </Badge>
          ) : null}
        </div>
        <StatusBadge kind="memory" status={item.status} className="shrink-0" />
      </div>

      <div className={cn("grid gap-1", inactive && "opacity-75")}>
        <h3
          className={cn(
            "line-clamp-2 text-[13.5px] font-semibold leading-snug tracking-tight text-foreground",
            superseded && "text-muted-foreground line-through decoration-muted-foreground/60",
            forgotten && "text-muted-foreground",
          )}
        >
          {item.title}
        </h3>
        <p className={cn("line-clamp-2 text-[12.5px] leading-relaxed text-muted-foreground", forgotten && "italic")}>
          {preview || "—"}
        </p>
      </div>

      {superseded || conflict ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {superseded ? (
            <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
              <CornerDownRight className="size-3.5 shrink-0" aria-hidden />
              <span className="truncate">
                Remplacé par{" "}
                <span className="font-medium text-foreground">
                  {supersededByTitle ? `« ${truncate(supersededByTitle, 70)} »` : "une version plus récente"}
                </span>
              </span>
            </span>
          ) : null}
          {conflict ? (
            <Badge tone="amber" icon={<Swords aria-hidden />} title="Contradiction détectée avec un autre élément">
              Conflit
            </Badge>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5" title="Confiance">
          <ScoreBar value={item.confidence} widthClassName="w-12" />
        </span>
        <span className="inline-flex items-center gap-1" title="Provenance">
          <Link2 className="size-3.5" aria-hidden />
          {plural(item.provenance_count, "source")}
        </span>
        {item.version > 1 ? (
          <span className="inline-flex items-center gap-1" title="Version">
            <GitBranch className="size-3.5" aria-hidden />v{item.version}
          </span>
        ) : null}
        <RelativeTime date={item.updated_at} className="ml-auto" />
      </div>
    </button>
  );
});

export function MemoryItemCardSkeleton() {
  return (
    <div className="grid gap-2.5 rounded-xl border border-border bg-card p-3.5" aria-hidden>
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-1.5">
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-5 w-16" />
        </div>
        <Skeleton className="h-5 w-16" />
      </div>
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-3.5 w-full" />
      <Skeleton className="h-3.5 w-3/5" />
      <div className="flex items-center gap-3">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="ml-auto h-3 w-20" />
      </div>
    </div>
  );
}
