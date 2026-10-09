"use client";

import Link from "next/link";
import { ArrowRight, Gavel, Link2 } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ScopeBadge } from "@/components/domain/scope-badge";
import { projectHref } from "@/components/layout/nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { MemoryCardFields } from "@/lib/api/features-ask";
import type { MemoryItem } from "@/lib/api/types";
import { formatDate, formatPercent, plural, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

const MAX_DECISIONS = 3;

export function memoryItemHref(slug: string, id: string): string {
  return `${projectHref(slug, "memory")}?item=${encodeURIComponent(id)}`;
}

/** Levels read better than near-identical percentages ("Confiance 90 %" on every line says nothing). */
function confidenceLevel(value: number): string {
  if (value >= 0.8) return "Confiance élevée";
  if (value >= 0.5) return "Confiance moyenne";
  return "À vérifier";
}

function confidenceExplanation(decision: MemoryItem): string {
  const reason = (decision as MemoryItem & MemoryCardFields).confidence_reason?.trim();
  const base = reason || "Estimée à l'extraction : formulation explicite (« Décision : »), type et fiabilité de la source.";
  return decision.status === "validated" ? `${base} Validée par une personne du projet.` : base;
}

/** Level 2 — the decisions ORBIT currently treats as valid (served to agents in priority). */
export function ActiveDecisions({ slug, decisions, className }: { slug: string; decisions: readonly MemoryItem[]; className?: string }) {
  const shown = decisions.slice(0, MAX_DECISIONS);
  const values = shown.map((d) => d.confidence);
  // Percentages only when they actually discriminate between decisions.
  const usePercent = values.length > 1 && Math.max(...values) - Math.min(...values) >= 0.15;

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Gavel className="size-4 text-brand" aria-hidden />
        <CardTitle>Décisions en vigueur</CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        {shown.length === 0 ? (
          <EmptyState
            size="sm"
            variant="plain"
            icon={<Gavel />}
            title="Aucune décision validée"
            description="Les décisions extraites des comptes rendus apparaissent ici une fois validées."
            action={
              <Link href={projectHref(slug, "inbox")} className="text-[13px] font-medium text-primary hover:underline">
                Revoir les propositions
              </Link>
            }
          />
        ) : (
          <ul className="divide-y divide-border">
            {shown.map((d) => (
              <li key={d.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-start gap-3">
                  <div className="grid min-w-0 flex-1 gap-1">
                    <div className="flex items-start gap-2">
                      <p className="min-w-0 flex-1 text-[13.5px] font-medium leading-snug text-foreground">{d.title}</p>
                      {d.classification >= 2 ? <ClassificationBadge level={d.classification} showLabel={false} /> : null}
                    </div>
                    {d.content && d.content.trim() !== d.title.trim() ? (
                      <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{truncate(d.content, 200)}</p>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted-foreground">
                      <ScopeBadge scope={d.scope} />
                      <span className="inline-flex items-center gap-1">
                        <Link2 className="size-3" aria-hidden />
                        {plural(d.provenance_count, "source")}
                      </span>
                      <SimpleTooltip content={confidenceExplanation(d)}>
                        <span tabIndex={0} className="cursor-help rounded underline decoration-dotted underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                          {usePercent ? `Confiance ${formatPercent(d.confidence)}` : confidenceLevel(d.confidence)}
                        </span>
                      </SimpleTooltip>
                      <span>En vigueur depuis le {formatDate(d.valid_from)}</span>
                    </div>
                  </div>
                  <Link
                    href={memoryItemHref(slug, d.id)}
                    className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                    aria-label={`Voir la décision : ${d.title}`}
                  >
                    Voir
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {shown.length > 0 ? (
        <div className="border-t border-border px-5 py-3">
          <Link
            href={`${projectHref(slug, "memory")}?kind=decision&status=validated`}
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Voir toutes les décisions
            <ArrowRight className="size-3" aria-hidden />
          </Link>
        </div>
      ) : null}
    </Card>
  );
}
