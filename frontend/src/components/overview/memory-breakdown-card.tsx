"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Brain } from "lucide-react";
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, Tooltip, XAxis, YAxis } from "recharts";

import { projectHref } from "@/components/layout/nav";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  CHART_COLORS,
  ChartContainer,
  ChartLegend,
  ChartTooltipContent,
  chartAxisProps,
  chartCursor,
} from "@/components/ui/chart";
import { EmptyState } from "@/components/ui/empty-state";
import type { Overview } from "@/lib/api/types";
import {
  MEMORY_SCOPE_META,
  MEMORY_SCOPES,
  MEMORY_STATUS_META,
  MEMORY_STATUSES,
  type MemoryStatus,
} from "@/lib/enums";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Fixed status → series color (color follows the entity, never its rank). */
const STATUS_COLORS: Record<MemoryStatus, string> = {
  validated: CHART_COLORS[0],
  proposed: CHART_COLORS[1],
  superseded: CHART_COLORS[2],
  obsolete: CHART_COLORS[3],
  forgotten: CHART_COLORS[4],
};

/** Display order of the donut segments (validated first). */
const STATUS_ORDER: readonly MemoryStatus[] = ["validated", "proposed", "superseded", "obsolete", "forgotten"];

interface Slice {
  status: MemoryStatus;
  label: string;
  value: number;
  color: string;
}

interface DonutTooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
  total: number;
}

function DonutTooltip({ active, payload, total }: DonutTooltipProps) {
  const slice = payload?.[0]?.payload as Slice | undefined;
  if (!active || !slice) return null;
  return (
    <div className="min-w-40 rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg">
      <div className="flex items-center gap-2">
        <span className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: slice.color }} aria-hidden />
        <span className="flex-1 text-muted-foreground">{slice.label}</span>
        <span className="font-medium tabular-nums text-foreground">{formatNumber(slice.value, 0)}</span>
      </div>
      <p className="mt-1 text-muted-foreground">{formatPercent(total > 0 ? slice.value / total : 0)} de la mémoire</p>
    </div>
  );
}

export function MemoryBreakdownCard({ slug, overview, className }: { slug: string; overview: Overview; className?: string }) {
  const slices = React.useMemo<Slice[]>(
    () =>
      STATUS_ORDER.filter((s) => MEMORY_STATUSES.includes(s)).map((status) => ({
        status,
        label: MEMORY_STATUS_META[status].label,
        value: overview.memory_by_status[status] ?? 0,
        color: STATUS_COLORS[status],
      })),
    [overview.memory_by_status],
  );
  const total = slices.reduce((acc, s) => acc + s.value, 0);
  const scopes = React.useMemo(
    () =>
      MEMORY_SCOPES.map((scope) => ({
        scope,
        label: MEMORY_SCOPE_META[scope].label,
        value: overview.memory_by_scope[scope] ?? 0,
      })),
    [overview.memory_by_scope],
  );
  const proposed = overview.memory_by_status.proposed ?? 0;

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Brain className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Mémoire du projet</CardTitle>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {formatNumber(total, 0)} élément{total > 1 ? "s" : ""}
        </span>
      </CardHeader>
      <CardContent className="flex-1">
        {total === 0 ? (
          <EmptyState
            size="sm"
            variant="plain"
            icon={<Brain />}
            title="Mémoire vide"
            description="Les décisions, besoins, contraintes et risques sont extraits automatiquement des sources ingérées."
          />
        ) : (
          <div className="grid gap-6 md:grid-cols-2">
            <section aria-label="Répartition par statut" className="grid gap-3">
              <h4 className="text-xs font-medium text-muted-foreground">Par statut</h4>
              <div className="relative">
                <ChartContainer height={172} label={`Mémoire par statut : ${slices.map((s) => `${s.label} ${s.value}`).join(", ")}`}>
                  <PieChart>
                    <Pie
                      data={slices.filter((s) => s.value > 0)}
                      dataKey="value"
                      nameKey="label"
                      innerRadius="64%"
                      outerRadius="92%"
                      stroke="var(--card)"
                      strokeWidth={2}
                      startAngle={90}
                      endAngle={-270}
                      isAnimationActive={false}
                    >
                      {slices
                        .filter((s) => s.value > 0)
                        .map((s) => (
                          <Cell key={s.status} fill={s.color} />
                        ))}
                    </Pie>
                    <Tooltip content={<DonutTooltip total={total} />} />
                  </PieChart>
                </ChartContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-xl font-semibold tabular-nums tracking-tight text-foreground">
                    {formatNumber(total, 0)}
                  </span>
                  <span className="text-[11px] text-muted-foreground">éléments</span>
                </div>
              </div>
              <ChartLegend items={slices.map((s) => ({ label: s.label, color: s.color, value: formatNumber(s.value, 0) }))} />
            </section>
            <section aria-label="Répartition par portée" className="grid content-start gap-3">
              <h4 className="text-xs font-medium text-muted-foreground">Par portée</h4>
              <ChartContainer
                height={172}
                label={`Mémoire par portée : ${scopes.map((s) => `${s.label} ${s.value}`).join(", ")}`}
              >
                <BarChart data={scopes} layout="vertical" margin={{ top: 4, right: 36, bottom: 4, left: 0 }} barCategoryGap={10}>
                  <XAxis type="number" hide allowDecimals={false} />
                  <YAxis type="category" dataKey="label" width={92} {...chartAxisProps} />
                  <Tooltip cursor={chartCursor} content={<ChartTooltipContent hideLabel />} />
                  <Bar
                    dataKey="value"
                    name="Éléments"
                    fill={CHART_COLORS[2]}
                    radius={[0, 4, 4, 0]}
                    maxBarSize={18}
                    isAnimationActive={false}
                  >
                    <LabelList dataKey="value" position="right" fill="var(--foreground)" fontSize={11} />
                  </Bar>
                </BarChart>
              </ChartContainer>
              {proposed > 0 ? (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-inset ring-amber-600/20 dark:bg-amber-400/10 dark:text-amber-100 dark:ring-amber-400/25">
                  <span className="font-semibold tabular-nums">{formatNumber(proposed, 0)}</span> proposition
                  {proposed > 1 ? "s" : ""} en attente de validation humaine.
                </p>
              ) : null}
            </section>
          </div>
        )}
      </CardContent>
      <CardFooter className="gap-4">
        <Link
          href={projectHref(slug, "memory")}
          className="inline-flex items-center gap-1 rounded font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Explorer la mémoire
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
        {proposed > 0 ? (
          <Link
            href={`${projectHref(slug, "memory")}?status=proposed`}
            className="rounded text-muted-foreground hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Revoir les propositions
          </Link>
        ) : null}
      </CardFooter>
    </Card>
  );
}
