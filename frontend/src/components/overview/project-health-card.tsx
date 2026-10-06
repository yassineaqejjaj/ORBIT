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
    <Card className={cn("bg-hero overflow-hidden rounded-4xl", className)}>
      <CardContent className="grid gap-4 py-5">
        <div className="flex flex-wrap items-start gap-3">
          <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", tone.soft)}>
            <Icon className="size-5" aria-hidden />
          </span>
          <div className="grid min-w-0 flex-1 gap-0.5">
            <p className="group-label">État du projet</p>
            <p className="text-2xl font-semibold tracking-tight text-foreground">{meta.label}</p>
            <p className="text-[13px] text-muted-foreground">
              {health.attentionCount === 0
                ? "Aucun élément ne demande votre attention."
                : `${health.attentionCount} élément${health.attentionCount > 1 ? "s demandent" : " demande"} votre attention.`}
            </p>
          </div>
        </div>

        {health.reasons.length > 0 ? (
          <ul className="grid gap-1 text-[13px]" aria-label="Raisons de l’état">
            {health.reasons.map((reason) => (
              <li key={reason} className={cn("flex items-start gap-2", tone.text)}>
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                {reason}
              </li>
            ))}
          </ul>
        ) : null}

        <ul className="grid gap-1.5 border-t border-border pt-3 text-[13px] sm:grid-cols-3" aria-label="Vérifications">
          {health.checks.map((check) => (
            <li key={check.label} className="flex items-start gap-2 text-foreground">
              {check.ok ? (
                <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="OK" />
              ) : (
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400" aria-label="À vérifier" />
              )}
              <span>{check.label}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
