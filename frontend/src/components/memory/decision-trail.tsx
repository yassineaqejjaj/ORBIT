"use client";

import * as React from "react";
import { ArrowRight, CheckCircle2, FileText, GitBranch, Pencil, PlusCircle, Replace, TriangleAlert } from "lucide-react";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { RelativeTime } from "@/components/domain/relative-time";
import { StatusBadge } from "@/components/domain/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/error-state";
import { useDecisionTrail } from "@/lib/api/hooks";
import type { TrailChainItem, TrailEntry } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  source: FileText,
  created: PlusCircle,
  edited: Pencil,
  validated: CheckCircle2,
  superseded: Replace,
  replaced_by: Replace,
  conflict_detected: TriangleAlert,
};

function Chain({ chain, onOpenItem }: { chain: TrailChainItem[]; onOpenItem: (id: string) => void }) {
  if (chain.length < 2) return null;
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Chaîne de remplacement">
      {chain.map((c, i) => (
        <li key={c.id} className="flex items-center gap-2">
          {i > 0 ? <ArrowRight className="size-4 text-muted-foreground" aria-hidden /> : null}
          <button
            type="button"
            onClick={() => onOpenItem(c.id)}
            aria-current={c.role === "current"}
            className={cn(
              "grid gap-0.5 rounded-lg border px-3 py-2 text-left text-sm",
              c.role === "current" ? "border-brand bg-brand/5" : "border-border hover:border-border-strong",
            )}
          >
            <span className="font-medium">{c.title}</span>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <StatusBadge kind="memory" status={c.status} size="sm" /> v{c.version} · {formatDateTime(c.valid_from)}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function Entry({ entry }: { entry: TrailEntry }) {
  const Icon = KIND_ICON[entry.kind] ?? GitBranch;
  return (
    <li className="relative grid gap-0.5 pl-8">
      <span className="absolute left-0 top-0.5 flex size-6 items-center justify-center rounded-full border border-border bg-surface text-muted-foreground">
        <Icon className="size-3.5" />
      </span>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-medium">{entry.label}</span>
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={entry.at} />
          {entry.actor ? ` · ${entry.actor}` : ""}
        </span>
      </div>
      {entry.detail ? <p className="text-[13px] text-muted-foreground">{entry.detail}</p> : null}
    </li>
  );
}

/** « Pourquoi ? » — what was recorded about how this item came to be, oldest first. */
export function DecisionTrailView({ slug, memoryId, onOpenItem }: { slug: string; memoryId: string; onOpenItem: (id: string) => void }) {
  const trail = useDecisionTrail(slug, memoryId);
  if (trail.isLoading) return <Skeleton className="mt-3 h-40 rounded-lg" />;
  if (trail.isError) return <ErrorState error={trail.error} onRetry={() => trail.refetch()} />;
  if (!trail.data) return null;
  const { why, chain, timeline } = trail.data;
  return (
    <div className="mt-3 grid gap-4">
      {trail.data.max_classification >= 2 ? <ClassificationBanner level={trail.data.max_classification} context="display" compact /> : null}
      <section className="grid gap-1 rounded-lg border border-border bg-muted/30 p-3 text-sm" aria-label="Justification">
        <p>{why.rationale ?? "Aucune justification n’a été enregistrée pour cet élément."}</p>
        <p className="text-xs text-muted-foreground">
          {why.decided_by ? `Décidé par ${why.decided_by} · ` : ""}
          Confiance {Math.round(why.confidence * 100)} %{why.confidence_reason ? ` — ${why.confidence_reason}` : ""}
        </p>
      </section>
      <Chain chain={chain} onOpenItem={onOpenItem} />
      {timeline.length === 0 ? (
        <p className="text-sm text-muted-foreground">Aucun événement enregistré.</p>
      ) : (
        <ol className="relative grid gap-3 before:absolute before:bottom-2 before:left-3 before:top-2 before:w-px before:bg-border">
          {timeline.map((entry, i) => (
            <Entry key={`${entry.at}-${entry.kind}-${i}`} entry={entry} />
          ))}
        </ol>
      )}
      <p className="text-xs text-muted-foreground">Seuls les éléments et sources auxquels vous avez accès sont retracés.</p>
    </div>
  );
}
