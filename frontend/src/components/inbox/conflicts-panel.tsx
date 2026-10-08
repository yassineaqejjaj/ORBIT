"use client";

import * as React from "react";
import { BadgeCheck, CircleCheck, FileText, GitCompareArrows, Lightbulb, Scale, ThumbsUp, Unlink } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { StatusBadge } from "@/components/domain/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useConflicts,
  useDismissConflict,
  useResolveConflict,
  type Conflict,
  type ConflictSide,
} from "@/lib/api/features-feed";
import { formatDate, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

type View = "open" | "resolved";

/** §D3 contradiction detection method. */
const METHOD_LABELS: Record<string, string> = {
  nli: "Modèle NLI local",
  llm: "LLM-juge",
  lexical: "Marqueurs lexicaux",
};

export function ConflictsPanel({ slug }: { slug: string }) {
  const [view, setView] = React.useState<View>("open");
  const conflicts = useConflicts(slug, view);
  const resolve = useResolveConflict(slug);
  const dismiss = useDismissConflict(slug);
  const [pending, setPending] = React.useState<{ conflict: Conflict; winner: ConflictSide } | null>(null);
  const [dismissing, setDismissing] = React.useState<Conflict | null>(null);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl<View>
          size="sm"
          value={view}
          onValueChange={setView}
          aria-label="Contradictions"
          options={[
            { value: "open", label: "À arbitrer" },
            { value: "resolved", label: "Historique" },
          ]}
        />
        <p className="text-xs text-muted-foreground">
          Vue côte à côte : conservez l&apos;item qui fait foi, l&apos;autre est marqué « remplacé ».
        </p>
      </div>

      {conflicts.isPending ? (
        <div className="grid gap-3" aria-busy="true" aria-label="Chargement des contradictions">
          {Array.from({ length: 2 }, (_, i) => (
            <Skeleton key={i} className="h-64 rounded-xl" />
          ))}
        </div>
      ) : conflicts.isError ? (
        <ErrorState error={conflicts.error} onRetry={() => void conflicts.refetch()} />
      ) : conflicts.data.length === 0 ? (
        <EmptyState
          icon={view === "open" ? <CircleCheck /> : <GitCompareArrows />}
          title={view === "open" ? "Aucune contradiction à arbitrer" : "Aucune contradiction traitée"}
          description={
            view === "open"
              ? "ORBIT signale ici les items qui se contredisent (valeurs, négations, remplacements en attente)."
              : "Les arbitrages et contradictions écartées apparaîtront ici."
          }
        />
      ) : (
        <ul className="grid gap-4">
          {conflicts.data.map((conflict) => (
            <li key={conflict.id}>
              <ConflictCard
                conflict={conflict}
                busy={resolve.isPending || dismiss.isPending}
                onKeep={(winner) => setPending({ conflict, winner })}
                onDismiss={() => setDismissing(conflict)}
              />
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title="Garder cet item ?"
        description={
          pending
            ? `« ${pending.winner.title} » est conservé ; l'autre item est marqué « remplacé » et n'est plus servi aux agents.`
            : undefined
        }
        confirmLabel="Garder celle-ci"
        reason="optional"
        reasonPlaceholder="Justification (facultatif)"
        loading={resolve.isPending}
        onConfirm={(reason) =>
          pending
            ? resolve
                .mutateAsync({ id: pending.conflict.id, winner_id: pending.winner.id, ...(reason ? { reason } : {}) })
                .then(() => {
                  toast.success("Contradiction arbitrée");
                  setPending(null);
                })
                .catch(() => undefined)
            : undefined
        }
      />
      <ConfirmDialog
        open={dismissing !== null}
        onOpenChange={(open) => !open && setDismissing(null)}
        title="Pas une contradiction ?"
        description="Les deux items restent actifs ; la relation est conservée comme simple lien."
        confirmLabel="Confirmer"
        reason="optional"
        reasonPlaceholder="Pourquoi ces items sont-ils compatibles ? (facultatif)"
        loading={dismiss.isPending}
        onConfirm={(reason) =>
          dismissing
            ? dismiss
                .mutateAsync({ id: dismissing.id, ...(reason ? { reason } : {}) })
                .then(() => {
                  toast.success("Contradiction écartée");
                  setDismissing(null);
                })
                .catch(() => undefined)
            : undefined
        }
      />
    </div>
  );
}

function ConflictCard({
  conflict,
  busy,
  onKeep,
  onDismiss,
}: {
  conflict: Conflict;
  busy: boolean;
  onKeep: (side: ConflictSide) => void;
  onDismiss: () => void;
}) {
  const open = conflict.status === "open";
  const resolution = conflict.resolution;
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center gap-2">
        <Scale className="size-4 text-muted-foreground" aria-hidden />
        <p className="text-[13px] font-medium">
          Contradiction détectée <RelativeTime date={conflict.detected_at} />
        </p>
        <Badge tone="neutral" size="sm">
          Similarité {formatPercent(conflict.similarity)}
        </Badge>
        {conflict.method ? (
          <Badge tone={conflict.method === "lexical" ? "neutral" : "violet"} size="sm">
            {METHOD_LABELS[conflict.method] ?? conflict.method}
            {conflict.score != null ? ` · ${formatPercent(conflict.score)}` : ""}
          </Badge>
        ) : null}
        {conflict.detail ? <span className="text-xs text-muted-foreground">{conflict.detail}</span> : null}
        {conflict.explanation && conflict.method !== "lexical" ? (
          <p className="w-full text-xs text-muted-foreground">{conflict.explanation}</p>
        ) : null}
        {!open ? (
          <Badge tone={conflict.status === "resolved" ? "green" : "neutral"} size="sm" className="ml-auto" dot>
            {conflict.status === "resolved" ? "Arbitrée" : "Écartée"}
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="grid gap-3 md:grid-cols-2">
          {[conflict.a, conflict.b].map((side) => (
            <SidePanel
              key={side.id}
              side={side}
              suggested={side.id === conflict.suggested_winner_id}
              winner={resolution?.winner_id === side.id}
              action={
                open ? (
                  <Button
                    size="sm"
                    variant={side.id === conflict.suggested_winner_id ? "primary" : "secondary"}
                    onClick={() => onKeep(side)}
                    disabled={busy}
                  >
                    <ThumbsUp aria-hidden />
                    Garder celle-ci
                  </Button>
                ) : null
              }
            />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
          <Lightbulb className="size-3.5 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">
            {open
              ? conflict.rationale
              : `${resolution?.status === "resolved" ? "Arbitrée" : "Écartée"} par ${resolution?.resolved_by || "—"} le ${formatDate(resolution?.resolved_at)}${resolution?.reason ? ` — ${resolution.reason}` : ""}`}
          </span>
          {open ? (
            <Button size="xs" variant="ghost" onClick={onDismiss} disabled={busy}>
              <Unlink aria-hidden />
              Pas une contradiction
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function SidePanel({
  side,
  suggested,
  winner,
  action,
}: {
  side: ConflictSide;
  suggested: boolean;
  winner: boolean;
  action: React.ReactNode;
}) {
  return (
    <section
      aria-label={side.title}
      className={cn(
        "grid content-start gap-2.5 rounded-lg border px-3 py-3",
        suggested || winner ? "border-brand/60 bg-brand-soft/30" : "border-border",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <MemoryKindBadge kind={side.kind} />
        <StatusBadge kind="memory" status={side.status} />
        <ClassificationBadge level={side.classification} showLabel={false} />
        {suggested && !winner ? (
          <Badge tone="blue" size="sm" icon={<Lightbulb />}>
            Suggérée
          </Badge>
        ) : null}
        {winner ? (
          <Badge tone="green" size="sm" icon={<BadgeCheck />}>
            Conservée
          </Badge>
        ) : null}
      </div>
      <p className="text-[13px] font-medium leading-snug">{side.title}</p>
      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/90">{side.content}</p>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <dt>Confiance</dt>
        <dd className="text-right tabular-nums text-foreground">{formatPercent(side.confidence)}</dd>
        <dt>En vigueur depuis</dt>
        <dd className="text-right text-foreground">{formatDate(side.valid_from)}</dd>
        <dt>Créé par</dt>
        <dd className="truncate text-right text-foreground">{side.created_by_label || "—"}</dd>
      </dl>
      <div className="grid gap-1">
        <p className="text-xs font-medium text-muted-foreground">Sources</p>
        {side.sources.length === 0 ? (
          <p className="text-xs text-muted-foreground">Aucune source rattachée.</p>
        ) : (
          <ul className="grid gap-1">
            {side.sources.slice(0, 3).map((s) => (
              <li key={s.id} className="flex items-start gap-1.5 text-xs">
                <FileText className="mt-px size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0">
                  <span className="font-medium">{s.document_title ?? (s.source_label || "Source")}</span>
                  {s.excerpt ? <span className="line-clamp-2 text-muted-foreground"> — {s.excerpt}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {action ? <div className="pt-1">{action}</div> : null}
    </section>
  );
}
