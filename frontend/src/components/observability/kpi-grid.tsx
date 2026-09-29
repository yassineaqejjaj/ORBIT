import * as React from "react";
import { Activity, Coins, Euro, Gauge, Star, Timer } from "lucide-react";

import { StarRating } from "@/components/explorer/star-rating";
import { StatCard } from "@/components/ui/stat-card";
import type { MetricsTotals } from "@/lib/api/types";
import { formatCost, formatMs, formatNumber, formatTokens, plural } from "@/lib/format";
import type { DailyPoint } from "@/lib/observability-utils";
import { cn } from "@/lib/utils";
import { SERIES_COLORS } from "./daily-charts";

const P95_TARGET_MS = 1500;

/** Minimal inline trend line (decorative: the full series is charted below). */
function Sparkline({ values, color, className }: { values: number[]; color: string; className?: string }) {
  if (values.length < 2 || values.every((v) => v === 0)) return null;
  const max = Math.max(...values, 1);
  const w = 100;
  const h = 24;
  const step = w / (values.length - 1);
  const points = values.map((v, i) => `${(i * step).toFixed(2)},${(h - 2 - (v / max) * (h - 4)).toFixed(2)}`);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cn("h-6 w-full overflow-visible", className)} aria-hidden>
      <polyline points={`0,${h} ${points.join(" ")} ${w},${h}`} fill={color} fillOpacity={0.1} stroke="none" />
      <polyline points={points.join(" ")} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

export interface KpiGridProps {
  totals: MetricsTotals | undefined;
  series: DailyPoint[];
  days: number;
  loading?: boolean;
}

/** Headline indicators of the period: requests, latency p50/p95, tokens, estimated cost, satisfaction. */
export function KpiGrid({ totals, series, days, loading }: KpiGridProps) {
  const requests = totals?.requests ?? 0;
  const perDay = days > 0 ? requests / days : 0;
  const p95 = totals?.p95_latency_ms ?? null;
  const p95Ok = typeof p95 === "number" && p95 > 0 ? p95 <= P95_TARGET_MS : null;
  const avgTokens = requests > 0 ? (totals?.tokens ?? 0) / requests : null;
  const costPerRequest = requests > 0 ? (totals?.cost_estimate ?? 0) / requests : null;
  const feedbackCount = totals?.feedback_count ?? 0;

  return (
    <section aria-label="Indicateurs clés" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatCard
        label="Requêtes de contexte"
        value={formatNumber(requests, 0)}
        icon={<Activity />}
        tone="teal"
        hint={`${formatNumber(perDay, 1)} par jour en moyenne`}
        loading={loading}
      >
        {!loading ? <Sparkline values={series.map((d) => d.requests)} color={SERIES_COLORS.requests} /> : null}
      </StatCard>
      <StatCard
        label="Latence p50"
        value={formatMs(totals?.p50_latency_ms)}
        icon={<Timer />}
        tone="blue"
        hint={`moyenne ${formatMs(totals?.avg_latency_ms)}`}
        loading={loading}
      />
      <StatCard
        label="Latence p95"
        value={formatMs(p95)}
        icon={<Gauge />}
        tone={p95Ok === false ? "amber" : "orange"}
        hint={
          p95Ok === null ? (
            "objectif < 1,5 s"
          ) : (
            <span className={cn(p95Ok ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400")}>
              {p95Ok ? "objectif < 1,5 s tenu" : "au-delà de l'objectif de 1,5 s"}
            </span>
          )
        }
        loading={loading}
      />
      <StatCard
        label="Tokens servis"
        value={formatTokens(totals?.tokens, { compact: true, unit: false })}
        icon={<Coins />}
        tone="violet"
        hint={avgTokens !== null ? `${formatNumber(Math.round(avgTokens), 0)} par requête` : "aucune requête"}
        loading={loading}
      >
        {!loading ? <Sparkline values={series.map((d) => d.tokens)} color={SERIES_COLORS.tokens} /> : null}
      </StatCard>
      <StatCard
        label="Coût estimé"
        value={formatCost(totals?.cost_estimate ?? 0)}
        icon={<Euro />}
        tone="green"
        hint={costPerRequest !== null ? `${formatCost(costPerRequest)} par requête` : "tarif configuré par 1 000 tokens"}
        loading={loading}
      />
      <StatCard
        label="Note moyenne"
        value={
          typeof totals?.avg_rating === "number" ? (
            <span>
              {formatNumber(totals.avg_rating, 1)}
              <span className="text-sm font-normal text-muted-foreground"> / 5</span>
            </span>
          ) : (
            "—"
          )
        }
        icon={<Star />}
        tone="amber"
        hint={feedbackCount > 0 ? plural(feedbackCount, "feedback") : "aucun feedback"}
        loading={loading}
      >
        {!loading && typeof totals?.avg_rating === "number" ? <StarRating value={totals.avg_rating} size="md" /> : null}
      </StatCard>
    </section>
  );
}
