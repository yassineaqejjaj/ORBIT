"use client";

import * as React from "react";
import { Activity, Coins, Timer } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import {
  CHART_COLORS,
  ChartContainer,
  ChartLegend,
  ChartTooltipContent,
  chartAxisProps,
  chartBarProps,
  chartCursor,
  chartGridProps,
  chartLineProps,
} from "@/components/ui/chart";
import { formatCompact, formatCost, formatDate, formatDayShort, formatMs, formatNumber, formatTokens } from "@/lib/format";
import type { DailyPoint } from "@/lib/observability-utils";
import { ChartCard, ChartHeadline } from "./chart-card";

const HEIGHT = 220;

/** Series colours: fixed per measure across the screen. */
export const SERIES_COLORS = {
  requests: CHART_COLORS[0],
  p50: CHART_COLORS[2],
  p95: CHART_COLORS[1],
  tokens: CHART_COLORS[4],
} as const;

interface DailyChartProps {
  data: DailyPoint[];
  loading?: boolean;
}

function tickInterval(length: number): number | "preserveStartEnd" {
  if (length <= 8) return 0;
  if (length <= 16) return 1;
  return "preserveStartEnd";
}

const dayLabel = (label: string | number) => formatDate(String(label));

/** Requests per day (bars). */
export function RequestsChart({ data, loading, total }: DailyChartProps & { total: number }) {
  const empty = !loading && data.every((d) => d.requests === 0);
  return (
    <ChartCard
      title="Requêtes de contexte par jour"
      description="Contextes assemblés pour les agents et depuis l'explorateur."
      icon={<Activity aria-hidden />}
      aside={<ChartHeadline value={formatNumber(total, 0)} label="sur la période" />}
      loading={loading}
      empty={empty}
      height={HEIGHT}
    >
      <ChartContainer height={HEIGHT} label={`Histogramme des requêtes par jour, ${formatNumber(total, 0)} au total`}>
        <BarChart data={data} margin={{ top: 8, right: 4, left: -8, bottom: 0 }}>
          <CartesianGrid {...chartGridProps} />
          <XAxis dataKey="date" {...chartAxisProps} tickFormatter={(v: string) => formatDayShort(v)} interval={tickInterval(data.length)} />
          <YAxis {...chartAxisProps} width={40} allowDecimals={false} />
          <Tooltip cursor={chartCursor} content={<ChartTooltipContent labelFormatter={dayLabel} valueFormatter={(v) => formatNumber(v, 0)} />} />
          <Bar dataKey="requests" name="Requêtes" fill={SERIES_COLORS.requests} {...chartBarProps} />
        </BarChart>
      </ChartContainer>
    </ChartCard>
  );
}

/** p50 / p95 latency per day (lines) — separate from the requests chart (one y-axis per chart). */
export function LatencyChart({ data, loading, p50, p95 }: DailyChartProps & { p50: number | null; p95: number | null }) {
  const empty = !loading && data.every((d) => d.p95 === null && d.p50 === null);
  return (
    <ChartCard
      title="Latence par jour"
      description="Médiane (p50) et 95e centile (p95) du temps d'assemblage. Objectif : p95 < 1,5 s."
      icon={<Timer aria-hidden />}
      aside={<ChartHeadline value={formatMs(p95)} label={`p95 · p50 ${formatMs(p50)}`} />}
      loading={loading}
      empty={empty}
      height={HEIGHT + 24}
    >
      <div className="grid gap-3">
        <ChartLegend
          items={[
            { label: "p50", color: SERIES_COLORS.p50 },
            { label: "p95", color: SERIES_COLORS.p95 },
          ]}
        />
        <ChartContainer height={HEIGHT} label={`Courbes de latence p50 et p95 par jour ; p95 sur la période ${formatMs(p95)}`}>
          <LineChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
            <CartesianGrid {...chartGridProps} />
            <XAxis dataKey="date" {...chartAxisProps} tickFormatter={(v: string) => formatDayShort(v)} interval={tickInterval(data.length)} />
            <YAxis {...chartAxisProps} width={52} tickFormatter={(v: number) => formatMs(v)} />
            <Tooltip cursor={{ stroke: "var(--border-strong)" }} content={<ChartTooltipContent labelFormatter={dayLabel} valueFormatter={(v) => formatMs(v)} />} />
            <Line dataKey="p50" name="p50" stroke={SERIES_COLORS.p50} connectNulls={false} {...chartLineProps} />
            <Line dataKey="p95" name="p95" stroke={SERIES_COLORS.p95} connectNulls={false} {...chartLineProps} />
          </LineChart>
        </ChartContainer>
      </div>
    </ChartCard>
  );
}

interface TokensTooltipProps {
  active?: boolean;
  label?: string | number;
  payload?: ReadonlyArray<{ payload?: DailyPoint }>;
}

function TokensTooltip({ active, label, payload }: TokensTooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="min-w-44 rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg">
      <p className="mb-1.5 font-medium text-foreground">{label !== undefined ? dayLabel(label) : null}</p>
      <ul className="grid gap-1">
        <li className="flex items-center gap-2">
          <span className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: SERIES_COLORS.tokens }} aria-hidden />
          <span className="flex-1 text-muted-foreground">Tokens servis</span>
          <span className="font-medium tabular-nums text-foreground">{formatNumber(point.tokens, 0)}</span>
        </li>
        <li className="flex items-center gap-2 pl-[18px]">
          <span className="flex-1 text-muted-foreground">Coût estimé</span>
          <span className="font-medium tabular-nums text-foreground">{formatCost(point.cost)}</span>
        </li>
        <li className="flex items-center gap-2 pl-[18px]">
          <span className="flex-1 text-muted-foreground">Requêtes</span>
          <span className="font-medium tabular-nums text-foreground">{formatNumber(point.requests, 0)}</span>
        </li>
      </ul>
    </div>
  );
}

/** Tokens served per day (area), with the estimated cost in the tooltip. */
export function TokensChart({ data, loading, total, cost }: DailyChartProps & { total: number; cost: number }) {
  const empty = !loading && data.every((d) => d.tokens === 0);
  const gradientId = React.useId().replace(/:/g, "");
  return (
    <ChartCard
      title="Tokens servis par jour"
      description="Volume de contexte transmis aux agents ; le coût est estimé au tarif configuré."
      icon={<Coins aria-hidden />}
      aside={<ChartHeadline value={formatTokens(total, { compact: true })} label={`≈ ${formatCost(cost)}`} />}
      loading={loading}
      empty={empty}
      height={HEIGHT}
    >
      <ChartContainer height={HEIGHT} label={`Aire des tokens servis par jour, ${formatNumber(total, 0)} tokens au total`}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
          <defs>
            <linearGradient id={`tokens-${gradientId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={SERIES_COLORS.tokens} stopOpacity={0.28} />
              <stop offset="100%" stopColor={SERIES_COLORS.tokens} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid {...chartGridProps} />
          <XAxis dataKey="date" {...chartAxisProps} tickFormatter={(v: string) => formatDayShort(v)} interval={tickInterval(data.length)} />
          <YAxis {...chartAxisProps} width={44} tickFormatter={(v: number) => formatCompact(v)} />
          <Tooltip cursor={{ stroke: "var(--border-strong)" }} content={<TokensTooltip />} />
          <Area
            dataKey="tokens"
            name="Tokens servis"
            type="monotone"
            stroke={SERIES_COLORS.tokens}
            strokeWidth={2}
            fill={`url(#tokens-${gradientId})`}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}
