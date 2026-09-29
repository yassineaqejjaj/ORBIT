"use client";

import * as React from "react";
import { Ban, Layers, Workflow } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Pie, PieChart, Tooltip, XAxis, YAxis } from "recharts";

import { CHART_COLORS, ChartContainer, ChartTooltipContent, chartAxisProps, chartCursor } from "@/components/ui/chart";
import { REASON_GROUP_META, REASON_CODE_META, type ReasonCode, type ReasonGroup } from "@/lib/enums";
import { formatMs, formatNumber, formatPercent } from "@/lib/format";
import type { InclusionSlice, ReasonRow, StageRow } from "@/lib/observability-utils";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";
import { ChartCard, ChartHeadline } from "./chart-card";
import { OTHER_FILL, useToneFill } from "./chart-tones";

const ROW_HEIGHT = 30;

function sliceColor(slice: InclusionSlice): string {
  return slice.slot >= 0 ? (CHART_COLORS[slice.slot] ?? OTHER_FILL) : OTHER_FILL;
}

/* -------------------------------------------------------------------------- */
/* Exclusions by reason                                                       */
/* -------------------------------------------------------------------------- */

export function ExclusionsChart({ rows, loading }: { rows: ReasonRow[]; loading?: boolean }) {
  const toneFill = useToneFill();
  const total = rows.reduce((acc, r) => acc + r.count, 0);
  const height = Math.max(140, rows.length * ROW_HEIGHT + 16);
  const groups = new Set(rows.map((r) => REASON_CODE_META[r.code as ReasonCode]?.group).filter(Boolean) as ReasonGroup[]);
  return (
    <ChartCard
      title="Exclusions par motif"
      description="Pourquoi des candidats n'ont pas été servis : gouvernance, qualité ou efficacité."
      icon={<Ban aria-hidden />}
      aside={<ChartHeadline value={formatNumber(total, 0)} label="exclusions" />}
      loading={loading}
      empty={!loading && rows.length === 0}
      emptyText="Aucune exclusion sur la période."
      height={220}
    >
      <div className="grid gap-3">
        <ChartContainer height={height} label={`Barres horizontales des exclusions par motif, ${formatNumber(total, 0)} au total`}>
          <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 40, left: 0, bottom: 0 }} barCategoryGap={6}>
            <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
            <XAxis type="number" {...chartAxisProps} allowDecimals={false} hide />
            <YAxis type="category" dataKey="short" {...chartAxisProps} width={104} tickMargin={6} />
            <Tooltip
              cursor={chartCursor}
              content={
                <ChartTooltipContent
                  labelFormatter={(label) => rows.find((r) => r.short === label)?.label ?? label}
                  valueFormatter={(v) => `${formatNumber(v, 0)} · ${formatPercent(total > 0 ? v / total : 0)}`}
                />
              }
            />
            <Bar dataKey="count" name="Exclusions" radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.code} fill={toneFill(r.tone)} />
              ))}
              <LabelList dataKey="count" position="right" offset={8} className="fill-foreground text-[11px] font-medium tabular-nums" />
            </Bar>
          </BarChart>
        </ChartContainer>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Familles de motifs">
          {(["governance", "quality", "efficiency"] as const)
            .filter((g) => groups.has(g))
            .map((g) => (
              <li key={g} className="flex items-center gap-1.5" title={REASON_GROUP_META[g].description}>
                <span className={cn("size-2.5 rounded-[3px]", toneClasses(REASON_GROUP_META[g].tone).bar)} aria-hidden />
                {REASON_GROUP_META[g].label}
                <span className="text-subtle-foreground">— {REASON_GROUP_META[g].description}</span>
              </li>
            ))}
        </ul>
      </div>
    </ChartCard>
  );
}

/* -------------------------------------------------------------------------- */
/* Inclusions by type                                                         */
/* -------------------------------------------------------------------------- */

export function InclusionsChart({ slices, loading }: { slices: InclusionSlice[]; loading?: boolean }) {
  const total = slices.reduce((acc, s) => acc + s.value, 0);
  const [active, setActive] = React.useState<string | null>(null);
  return (
    <ChartCard
      title="Inclusions par type"
      description="Nature des éléments servis aux agents."
      icon={<Layers aria-hidden />}
      loading={loading}
      empty={!loading && slices.length === 0}
      emptyText="Aucun élément servi sur la période."
      height={220}
    >
      <div className="flex flex-col items-center gap-4 sm:flex-row lg:flex-col 2xl:flex-row">
        <div className="relative size-44 shrink-0">
          <ChartContainer height={176} label={`Anneau des inclusions par type, ${formatNumber(total, 0)} éléments`}>
            <PieChart>
              <Tooltip content={<ChartTooltipContent hideLabel valueFormatter={(v) => `${formatNumber(v, 0)} · ${formatPercent(total > 0 ? v / total : 0)}`} />} />
              <Pie
                data={slices}
                dataKey="value"
                nameKey="label"
                innerRadius={54}
                outerRadius={84}
                paddingAngle={slices.length > 1 ? 1.5 : 0}
                stroke="var(--card)"
                strokeWidth={2}
                startAngle={90}
                endAngle={-270}
                isAnimationActive={false}
                onMouseEnter={(_, index) => setActive(slices[index]?.key ?? null)}
                onMouseLeave={() => setActive(null)}
              >
                {slices.map((s) => (
                  <Cell key={s.key} fill={sliceColor(s)} opacity={active && active !== s.key ? 0.45 : 1} />
                ))}
              </Pie>
            </PieChart>
          </ChartContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-xl font-semibold text-foreground">{formatNumber(total, 0)}</span>
            <span className="text-[11px] text-muted-foreground">éléments</span>
          </div>
        </div>
        <ul className="grid w-full min-w-0 gap-1.5 text-xs" aria-label="Légende des inclusions">
          {slices.map((s) => (
            <li
              key={s.key}
              className={cn("flex items-center gap-2 rounded px-1 py-0.5", active === s.key && "bg-muted")}
              onMouseEnter={() => setActive(s.key)}
              onMouseLeave={() => setActive(null)}
              title={s.members.length > 1 ? s.members.join(", ") : undefined}
            >
              <span className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: sliceColor(s) }} aria-hidden />
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{s.label}</span>
              <span className="font-medium tabular-nums text-foreground">{formatNumber(s.value, 0)}</span>
              <span className="w-10 text-right tabular-nums text-subtle-foreground">{formatPercent(s.ratio)}</span>
            </li>
          ))}
        </ul>
      </div>
    </ChartCard>
  );
}

/* -------------------------------------------------------------------------- */
/* Average stage latency                                                      */
/* -------------------------------------------------------------------------- */

export function StageLatencyChart({ rows, loading }: { rows: StageRow[]; loading?: boolean }) {
  const total = rows.reduce((acc, r) => acc + r.ms, 0);
  const height = Math.max(140, rows.length * ROW_HEIGHT + 16);
  const slowest = rows.reduce<StageRow | null>((max, r) => (!max || r.ms > max.ms ? r : max), null);
  return (
    <ChartCard
      title="Latence moyenne par étape"
      description="Où se passe le temps d'assemblage, étape par étape."
      icon={<Workflow aria-hidden />}
      aside={<ChartHeadline value={formatMs(total)} label="somme des moyennes" />}
      loading={loading}
      empty={!loading && (rows.length === 0 || total === 0)}
      height={220}
    >
      <ChartContainer
        height={height}
        label={`Barres horizontales de la latence moyenne par étape${slowest ? ` ; étape la plus lente : ${slowest.label} (${formatMs(slowest.ms)})` : ""}`}
      >
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 56, left: 0, bottom: 0 }} barCategoryGap={6}>
          <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
          <XAxis type="number" {...chartAxisProps} hide />
          <YAxis type="category" dataKey="label" {...chartAxisProps} width={104} tickMargin={6} />
          <Tooltip
            cursor={chartCursor}
            content={
              <ChartTooltipContent
                labelFormatter={(label) => {
                  const row = rows.find((r) => r.label === label);
                  return row?.description ? `${label} — ${row.description}` : label;
                }}
                valueFormatter={(v) => `${formatMs(v)} · ${formatPercent(total > 0 ? v / total : 0)}`}
              />
            }
          />
          <Bar dataKey="ms" name="Latence moyenne" radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.key} fill={CHART_COLORS[2]} fillOpacity={slowest && r.key === slowest.key ? 1 : 0.55} />
            ))}
            <LabelList
              dataKey="ms"
              position="right"
              offset={8}
              formatter={(v) => formatMs(Number(v))}
              className="fill-foreground text-[11px] font-medium tabular-nums"
            />
          </Bar>
        </BarChart>
      </ChartContainer>
    </ChartCard>
  );
}
