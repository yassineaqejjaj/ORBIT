"use client";

/**
 * Recharts helpers aligned with the ORBIT design tokens (theme-aware CSS variables).
 * Usage:
 *   <ChartContainer height={240} label="Requêtes par jour">
 *     <LineChart data={series}>
 *       <CartesianGrid {...chartGridProps} />
 *       <XAxis dataKey="date" {...chartAxisProps} tickFormatter={formatDayShort} />
 *       <YAxis {...chartAxisProps} width={40} />
 *       <Tooltip content={<ChartTooltipContent labelFormatter={formatDayShort} />} cursor={chartCursor} />
 *       <Line dataKey="requests" name="Requêtes" stroke={CHART_COLORS[0]} {...chartLineProps} />
 *     </LineChart>
 *   </ChartContainer>
 * Rules: one y-axis per chart, fixed series order (CHART_COLORS), legend for ≥ 2 series, text in text tokens.
 */
import * as React from "react";
import { ResponsiveContainer } from "recharts";

import { CHART_COLORS } from "@/lib/tones";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

export { CHART_COLORS };

export interface ChartContainerProps {
  /** Pixel height of the plot area. */
  height?: number;
  /** Accessible description of the chart (announced as an image label). */
  label: string;
  className?: string;
  children: React.ReactElement;
}

export function ChartContainer({ height = 240, label, className, children }: ChartContainerProps) {
  return (
    <div role="img" aria-label={label} className={cn("w-full select-none text-xs", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

/** Spread on <XAxis>/<YAxis>: recessive axes, token colors. */
export const chartAxisProps = {
  stroke: "var(--chart-axis)",
  tick: { fill: "var(--muted-foreground)", fontSize: 11 },
  tickLine: false,
  axisLine: false,
  tickMargin: 8,
} as const;

/** Spread on <CartesianGrid>: horizontal hairlines only. */
export const chartGridProps = {
  stroke: "var(--chart-grid)",
  vertical: false,
} as const;

/** Spread on <Line>: 2px lines, markers only on hover. */
export const chartLineProps = {
  type: "monotone",
  strokeWidth: 2,
  dot: false,
  activeDot: { r: 4, strokeWidth: 2, stroke: "var(--card)" },
  isAnimationActive: false,
} as const;

/** Spread on <Bar>: rounded data-ends. */
export const chartBarProps = {
  radius: [4, 4, 0, 0] as [number, number, number, number],
  isAnimationActive: false,
  maxBarSize: 36,
} as const;

/** Tooltip cursor (crosshair band). */
export const chartCursor = { fill: "var(--muted)", opacity: 0.6, stroke: "var(--border-strong)" } as const;

export interface ChartTooltipPayloadItem {
  name?: string | number;
  value?: number | string | ReadonlyArray<number | string>;
  color?: string;
  fill?: string;
  stroke?: string;
  dataKey?: string | number | ((obj: unknown) => unknown);
}

export interface ChartTooltipContentProps {
  /** Injected by Recharts. */
  active?: boolean;
  /** Injected by Recharts. */
  payload?: ReadonlyArray<ChartTooltipPayloadItem>;
  /** Injected by Recharts. */
  label?: string | number;
  valueFormatter?: (value: number, name: string) => React.ReactNode;
  labelFormatter?: (label: string | number) => React.ReactNode;
  hideLabel?: boolean;
  /** Optional unit appended to values ("ms", "tokens"). */
  unit?: string;
}

/** Tooltip body: label, then one row per series (swatch + name + value in text tokens). */
export function ChartTooltipContent({
  active,
  payload,
  label,
  valueFormatter,
  labelFormatter,
  hideLabel,
  unit,
}: ChartTooltipContentProps) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="min-w-40 rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg">
      {!hideLabel && label !== undefined ? (
        <p className="mb-1.5 font-medium text-foreground">{labelFormatter ? labelFormatter(label) : label}</p>
      ) : null}
      <ul className="grid gap-1">
        {payload.map((item, i) => {
          const name = String(item.name ?? item.dataKey ?? "");
          const raw = Array.isArray(item.value) ? item.value[0] : item.value;
          const num = typeof raw === "number" ? raw : Number(raw);
          const color = item.color ?? item.stroke ?? item.fill ?? CHART_COLORS[i % CHART_COLORS.length];
          return (
            <li key={`${name}-${i}`} className="flex items-center gap-2">
              <span className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: color }} aria-hidden />
              <span className="flex-1 truncate text-muted-foreground">{name}</span>
              <span className="font-medium tabular-nums text-foreground">
                {Number.isFinite(num) ? (valueFormatter ? valueFormatter(num, name) : formatNumber(num)) : String(raw ?? "—")}
                {unit ? <span className="ml-0.5 font-normal text-muted-foreground">{unit}</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export interface ChartLegendItem {
  label: string;
  color: string;
  /** Optional value shown after the label. */
  value?: React.ReactNode;
}

/** Static legend (always present for ≥ 2 series). */
export function ChartLegend({ items, className }: { items: ReadonlyArray<ChartLegendItem>; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground", className)}>
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ backgroundColor: item.color }} aria-hidden />
          <span>{item.label}</span>
          {item.value !== undefined ? <span className="font-medium tabular-nums text-foreground">{item.value}</span> : null}
        </li>
      ))}
    </ul>
  );
}
