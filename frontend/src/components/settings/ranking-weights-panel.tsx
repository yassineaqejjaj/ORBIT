"use client";

import { RotateCcw, Scale, Undo2, Wand2 } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import { evalApi, type RankingWeights, type WeightKey, useEvalMutation, useRankingWeights } from "@/lib/api/features-eval";
import { formatDateTime } from "@/lib/format";

const LABELS: Record<WeightKey, string> = {
  rrf: "Rang de recherche fusionné",
  dense: "Similarité sémantique",
  freshness: "Fraîcheur",
  type: "Type d'élément (décision, contrainte…)",
  terms: "Mots de la tâche",
};
const KEYS = Object.keys(LABELS) as WeightKey[];
const REASONS = { learn: "Ajustement d'après les retours", revert: "Annulation", reset: "Réinitialisation" } as const;
const OUTCOMES = {
  adjusted: "Poids ajustés d'après les retours.",
  unchanged: "Pas assez de retours (ou aucun changement) : poids inchangés.",
  reverted: "Ajustement annulé.",
  reset: "Poids par défaut rétablis.",
} as const;

function fmt(value: number): string {
  return value.toFixed(3);
}

/** Paramètres → Évaluation: per-project ranking weights learned from feedback (§E2), bounded and reversible. */
export function RankingWeightsPanel() {
  const { slug, isOwner } = useCurrentProject();
  const weights = useRankingWeights(slug);
  const onDone = (out: unknown) => {
    const outcome = (out as RankingWeights).outcome;
    if (outcome) toast.success(OUTCOMES[outcome]);
  };
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const learn = useEvalMutation(slug, () => evalApi.learn(slug));
  const revert = useEvalMutation(slug, (id: string) => evalApi.revert(slug, id));
  const reset = useEvalMutation(slug, () => evalApi.reset(slug));

  if (weights.isLoading) return <Skeleton className="h-64 rounded-xl" />;
  if (weights.error || !weights.data) return <ErrorState error={weights.error} onRetry={() => weights.refetch()} />;
  const data = weights.data;

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Scale className="size-4" aria-hidden />
            Poids du classement
          </CardTitle>
          <CardDescription>
            Appris à partir des 👍/👎, des signalements, des épingles et des décisions de tri ; chaque poids reste à ±
            {fmt(data.max_delta)} de sa valeur par défaut (au moins {data.min_signals} signaux requis).
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {!data.enabled ? <Alert tone="blue">Apprentissage désactivé (ORBIT_RANKING_LEARNING) : poids par défaut.</Alert> : null}
          <ul className="grid gap-2.5">
            {KEYS.map((key) => {
              const [low, high] = data.bounds[key];
              const value = data.weights[key];
              const changed = Math.abs(value - data.defaults[key]) > 1e-4;
              return (
                <li key={key} className="grid gap-1">
                  <div className="flex items-baseline justify-between gap-2 text-[13px]">
                    <span>{LABELS[key]}</span>
                    <span className="font-mono text-xs">
                      {fmt(value)}
                      {changed ? <span className="text-muted-foreground"> (défaut {fmt(data.defaults[key])})</span> : null}
                    </span>
                  </div>
                  <div className="relative h-1.5 rounded-full bg-surface" aria-hidden>
                    <div
                      className="absolute h-full rounded-full bg-border"
                      style={{ left: `${low * 100}%`, width: `${(high - low) * 100}%` }}
                    />
                    <div className="absolute h-full w-1 rounded-full bg-brand" style={{ left: `calc(${value * 100}% - 2px)` }} />
                  </div>
                </li>
              );
            })}
          </ul>
          {isOwner ? (
            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" disabled={!data.enabled || learn.isPending} onClick={() => learn.mutate(undefined, { onSuccess: onDone, onError })}>
                <Wand2 aria-hidden />
                Ajuster d&apos;après les retours
              </Button>
              <Button size="sm" variant="outline" disabled={reset.isPending} onClick={() => reset.mutate(undefined, { onSuccess: onDone, onError })}>
                <RotateCcw aria-hidden />
                Poids par défaut
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Journal des ajustements</CardTitle>
          <CardDescription>Chaque changement est journalisé dans l&apos;audit et peut être annulé.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.history.length === 0 ? <p className="text-xs text-muted-foreground">Aucun ajustement : poids par défaut.</p> : null}
          <ul className="grid gap-2">
            {data.history.map((change) => (
              <li key={change.id} className="flex items-start justify-between gap-2 rounded-md border border-border px-3 py-2">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-1.5 text-[13px]">
                    {REASONS[change.reason]}
                    {change.reverted_at ? <Badge tone="neutral" size="sm">annulé</Badge> : null}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDateTime(change.created_at)} · {change.actor}
                    {change.reason === "learn"
                      ? ` · ${change.signals.positive ?? 0} signaux positifs, ${change.signals.negative ?? 0} négatifs`
                      : ""}
                  </p>
                  <p className="font-mono text-[11px] text-muted-foreground">
                    {KEYS.filter((k) => Math.abs(change.after[k] - change.before[k]) > 1e-4)
                      .map((k) => `${k} ${fmt(change.before[k])}→${fmt(change.after[k])}`)
                      .join(" · ") || "—"}
                  </p>
                </div>
                {isOwner && change.reason === "learn" && !change.reverted_at ? (
                  <Button size="xs" variant="ghost" disabled={revert.isPending} onClick={() => revert.mutate(change.id, { onSuccess: onDone, onError })}>
                    <Undo2 aria-hidden />
                    Annuler
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
