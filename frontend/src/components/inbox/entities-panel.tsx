"use client";

import * as React from "react";
import { Combine, Split, Tags } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useEntities, useEntitySuggestions, useMergeEntity, useUnmergeEntity } from "@/lib/api/hooks";
import type { Entity } from "@/lib/api/types";
import { formatPercent } from "@/lib/format";

/** §D2 entity resolution: suggested merges (never automatic) and merged entities (undo). */
export function EntitiesPanel({ slug }: { slug: string }) {
  const suggestions = useEntitySuggestions(slug);
  const entities = useEntities(slug);
  const merge = useMergeEntity(slug);
  const unmerge = useUnmergeEntity(slug);

  const onMerge = (target: Entity, source: Entity) =>
    merge.mutate(
      { targetId: target.id, sourceId: source.id },
      {
        onSuccess: () => toast.success(`« ${source.name} » fusionnée dans « ${target.name} »`),
        onError: (error) => toast.error(error.message),
      },
    );

  return (
    <div className="grid gap-6">
      <section className="grid gap-3" aria-labelledby="entity-suggestions">
        <h2 id="entity-suggestions" className="text-sm font-semibold">
          Fusions suggérées
        </h2>
        {suggestions.isLoading ? (
          <Skeleton className="h-24" />
        ) : suggestions.isError ? (
          <ErrorState error={suggestions.error} onRetry={() => suggestions.refetch()} />
        ) : !suggestions.data?.length ? (
          <EmptyState
            icon={<Combine />}
            title="Aucune fusion suggérée"
            description="ORBIT propose de fusionner les entités qui désignent probablement la même chose (sigle, forme proche)."
          />
        ) : (
          suggestions.data.map((s) => (
            <Card key={`${s.a.id}-${s.b.id}`}>
              <CardHeader className="flex-row flex-wrap items-center gap-2">
                <Combine className="size-4 text-muted-foreground" aria-hidden />
                <p className="text-[13px] font-medium">
                  « {s.a.name} » et « {s.b.name} »
                </p>
                <Badge tone="neutral" size="sm">
                  Score {formatPercent(s.score)}
                </Badge>
                <span className="text-xs text-muted-foreground">{s.reason}</span>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={merge.isPending} onClick={() => onMerge(s.a, s.b)}>
                  Garder « {s.a.name} »
                </Button>
                <Button size="sm" variant="outline" disabled={merge.isPending} onClick={() => onMerge(s.b, s.a)}>
                  Garder « {s.b.name} »
                </Button>
              </CardContent>
            </Card>
          ))
        )}
      </section>

      <section className="grid gap-3" aria-labelledby="entity-list">
        <h2 id="entity-list" className="text-sm font-semibold">
          Entités et alias
        </h2>
        {entities.isLoading ? (
          <Skeleton className="h-24" />
        ) : entities.isError ? (
          <ErrorState error={entities.error} onRetry={() => entities.refetch()} />
        ) : !entities.data?.length ? (
          <EmptyState
            icon={<Tags />}
            title="Aucune entité"
            description="Les entités et leurs alias élargissent la recherche : « PMR » retrouve « personne à mobilité réduite »."
          />
        ) : (
          <ul className="grid gap-2">
            {entities.data.map((entity) => {
              const merged = entity.aliases.filter((a) => a.merged_from_id);
              const origins = [...new Set(merged.map((a) => a.merged_from_id as string))];
              return (
                <li key={entity.id} className="rounded-md border border-border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-medium">{entity.name}</span>
                    <Badge tone="neutral" size="sm">
                      {entity.kind}
                    </Badge>
                    {entity.aliases.map((a) => (
                      <Badge key={a.alias} tone={a.merged_from_id ? "violet" : "sky"} size="sm">
                        {a.alias}
                      </Badge>
                    ))}
                  </div>
                  {origins.map((origin) => (
                    <Button
                      key={origin}
                      size="sm"
                      variant="ghost"
                      className="mt-2"
                      disabled={unmerge.isPending}
                      onClick={() =>
                        unmerge.mutate(origin, {
                          onSuccess: (restored) => toast.success(`Fusion de « ${restored.name} » annulée`),
                          onError: (error) => toast.error(error.message),
                        })
                      }
                    >
                      <Split aria-hidden />
                      Annuler la fusion ({merged.filter((a) => a.merged_from_id === origin).map((a) => a.alias).join(", ")})
                    </Button>
                  ))}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
