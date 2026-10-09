"use client";

import { CircleAlert, CircleCheck, OctagonAlert, TriangleAlert } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { Overview } from "@/lib/api/types";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";
import { computeProjectHealth, HEALTH_META, type HealthLevel } from "./project-health";

const LEVEL_ICON: Record<HealthLevel, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  good: CircleCheck,
  watch: TriangleAlert,
  action: CircleAlert,
  critical: OctagonAlert,
};

/** Level 1 — "Est-ce que mon projet fonctionne correctement ?" */
export function ProjectHealthCard({ overview, className }: { overview: Overview; className?: string }) {
  const health = computeProjectHealth(overview);
  const meta = HEALTH_META[health.level];
  const tone = toneClasses(meta.tone);
  const Icon = LEVEL_ICON[health.level];

  return (
    <Card className={cn("bg-hero overflow-hidden rounded-3xl", className)}>
      <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-xl", tone.soft)}>
            <Icon className="size-[18px]" aria-hidden />
          </span>
          <div className="grid min-w-0 gap-0.5">
            <p className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-lg font-semibold tracking-tight text-foreground">{meta.label}</span>
              <span className="text-[13px] text-muted-foreground">
                {health.attentionCount === 0
                  ? "Aucun élément ne demande votre attention."
                  : `${health.attentionCount} élément${health.attentionCount > 1 ? "s demandent" : " demande"} votre attention.`}
              </span>
            </p>
            {health.reasons.length > 0 ? (
              <ul className="flex flex-wrap gap-x-4 gap-y-0.5 text-[13px]" aria-label="Raisons de l’état">
                {health.reasons.map((reason) => (
                  <li key={reason} className={cn("flex items-center gap-1.5", tone.text)}>
                    <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
                    {reason}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>

        <ul className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] lg:ml-auto" aria-label="Vérifications">
          {health.checks.map((check) => (
            <li key={check.label} className="flex items-center gap-1.5 text-foreground">
              {check.ok ? (
                <CircleCheck className="size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="OK" />
              ) : (
                <TriangleAlert className="size-3.5 shrink-0 text-amber-600 dark:text-amber-400" aria-label="À vérifier" />
              )}
              <span>{check.label}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
