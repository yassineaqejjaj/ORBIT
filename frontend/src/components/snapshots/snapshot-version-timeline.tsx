"use client";

import * as React from "react";
import { Coins, CornerLeftUp, Fingerprint, Layers, UserRound } from "lucide-react";

import { IntentBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { SnapshotSummary } from "@/lib/api/types";
import { formatDateTime, formatNumber, formatTokens } from "@/lib/format";
import { cn } from "@/lib/utils";

import { shortHash } from "./snapshot-utils";

export interface SnapshotVersionTimelineProps {
  versions: readonly SnapshotSummary[];
  selected: number | null;
  latest: number | null;
  onSelect: (version: number) => void;
  /** Versions highlighted by the compare mode. */
  compare?: { from: number; to: number } | null;
}

/** Vertical timeline of the versions of a snapshot (most recent first). */
export function SnapshotVersionTimeline({ versions, selected, latest, onSelect, compare }: SnapshotVersionTimelineProps) {
  return (
    <ol className="relative grid gap-0" aria-label="Versions">
      {versions.map((v, index) => {
        const active = compare ? v.version === compare.from || v.version === compare.to : v.version === selected;
        const compareRole = compare ? (v.version === compare.from ? "Départ" : v.version === compare.to ? "Arrivée" : null) : null;
        const last = index === versions.length - 1;
        return (
          <li key={v.id} className="relative grid grid-cols-[1.75rem_minmax(0,1fr)] gap-2 pb-3 last:pb-0">
            {!last ? <span className="absolute bottom-0 left-[13px] top-7 w-px bg-border" aria-hidden /> : null}
            <span
              className={cn(
                "relative z-10 mt-2 flex size-7 items-center justify-center rounded-full font-mono text-[10.5px] font-semibold ring-4 ring-background",
                active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
              )}
              aria-hidden
            >
              v{v.version}
            </span>
            <button
              type="button"
              onClick={() => onSelect(v.version)}
              aria-current={active ? "true" : undefined}
              className={cn(
                "grid min-w-0 gap-1.5 rounded-lg border p-3 text-left transition-[border-color,background-color,box-shadow]",
                "hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active ? "border-brand/50 bg-brand-soft/40 shadow-xs ring-1 ring-brand/25" : "border-border bg-card",
              )}
            >
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="text-[13px] font-semibold text-foreground">Version {v.version}</span>
                {v.version === latest ? (
                  <Badge tone="teal" dot>
                    Dernière
                  </Badge>
                ) : null}
                {compareRole ? (
                  <Badge tone="blue" variant="outline">
                    {compareRole}
                  </Badge>
                ) : null}
                <span className="ml-auto text-[11px] text-muted-foreground" title={formatDateTime(v.created_at)}>
                  <RelativeTime date={v.created_at} />
                </span>
              </span>
              <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground" title={v.task}>
                {v.task || "Tâche non renseignée"}
              </span>
              <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-muted-foreground">
                <span className="inline-flex min-w-0 items-center gap-1">
                  <UserRound className="size-3 shrink-0" aria-hidden />
                  <span className="truncate">{v.created_by_label || "Inconnu"}</span>
                </span>
                <IntentBadge value={v.intent} />
              </span>
              <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-1" title="Tokens">
                  <Coins className="size-3" aria-hidden />
                  {formatTokens(v.token_count, { compact: true })}
                </span>
                <span className="inline-flex items-center gap-1" title="Éléments">
                  <Layers className="size-3" aria-hidden />
                  {formatNumber(v.items_count, 0)} élém.
                </span>
                <span className="inline-flex items-center gap-1 font-mono" title={v.content_hash}>
                  <Fingerprint className="size-3" aria-hidden />
                  {shortHash(v.content_hash, 8)}
                </span>
                {v.parent_version ? (
                  <span className="inline-flex items-center gap-1" title="Version parente">
                    <CornerLeftUp className="size-3" aria-hidden />
                    dérivée de v{v.parent_version}
                  </span>
                ) : null}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function SnapshotVersionTimelineSkeleton() {
  return (
    <div className="grid gap-3" aria-hidden>
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-2">
          <Skeleton className="mt-2 size-7 rounded-full" />
          <Skeleton className="h-28 rounded-lg" />
        </div>
      ))}
    </div>
  );
}
