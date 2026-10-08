"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Activity, Download, FlaskConical, Loader2, Lock, Telescope } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import { useExportTraces, useMetrics } from "@/lib/api/hooks";
import { formatNumber, plural } from "@/lib/format";
import {
  DEFAULT_PERIOD,
  PERIOD_OPTIONS,
  buildInclusionSlices,
  buildReasonRows,
  buildStageRows,
  densifySeries,
  isPeriod,
  type PeriodDays,
} from "@/lib/observability-utils";
import { cn } from "@/lib/utils";
import { ExclusionsChart, InclusionsChart, StageLatencyChart } from "./breakdown-charts";
import { LatencyChart, RequestsChart, TokensChart } from "./daily-charts";
import { DailyTable } from "./daily-table";
import { CacheStats } from "./cache-stats";
import { IngestionStats } from "./ingestion-stats";
import { KpiGrid } from "./kpi-grid";
import { RequestLog } from "./request-log";
import { AgentsTable, TopSourcesTable } from "./usage-tables";

const PERIOD_PARAM = "days";

function parsePeriod(value: string | null): PeriodDays {
  const n = value ? Number.parseInt(value, 10) : Number.NaN;
  return isPeriod(n) ? n : DEFAULT_PERIOD;
}

/** Period selector mirrored in `?days=` (deep-linkable, survives reloads). */
function usePeriodParam(): [PeriodDays, (days: PeriodDays) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const period = parsePeriod(searchParams.get(PERIOD_PARAM));
  const setPeriod = React.useCallback(
    (days: PeriodDays) => {
      const params = new URLSearchParams(searchParams.toString());
      if (days === DEFAULT_PERIOD) params.delete(PERIOD_PARAM);
      else params.set(PERIOD_PARAM, String(days));
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );
  return [period, setPeriod];
}

function ExportTracesButton({
  slug,
  days,
  variant = "secondary",
}: {
  slug: string;
  days: number;
  variant?: "primary" | "secondary";
}) {
  const exportTraces = useExportTraces(slug, { meta: { silentError: true } });
  const run = () =>
    exportTraces.mutate(
      { days },
      {
        onSuccess: (text) => {
          const lines = text.split("\n").filter((l) => l.trim()).length;
          toast.success("Export des traces téléchargé", {
            description: `${plural(lines, "trace")} de contexte sur ${days} jours (NDJSON).`,
          });
        },
        onError: (error) => toast.error("Export impossible", { description: errorMessage(error) }),
      },
    );
  return (
    <Button
      variant={variant}
      size="sm"
      onClick={run}
      loading={exportTraces.isPending}
      leftIcon={<Download aria-hidden />}
    >
      Exporter les traces (NDJSON)
    </Button>
  );
}

function ForgeNote({ slug, days, isOwner }: { slug: string; days: number; isOwner: boolean }) {
  return (
    <Card>
      <CardHeader className="flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="grid gap-1">
          <CardTitle className="flex items-center gap-2">
            <FlaskConical className="size-4 text-primary" aria-hidden />
            Évaluation hors ligne (FORGE)
          </CardTitle>
          <CardDescription className="max-w-3xl text-xs leading-relaxed">
            L&apos;export NDJSON (schéma <code className="font-mono">orbit.trace.v1</code>) contient une ligne JSON par
            requête de contexte : la tâche et ses paramètres, l&apos;agent et l&apos;utilisateur, le contexte servi, les
            décisions de sélection (retenus avec citations et scores, exclus avec leur motif), les temps de chaque étape,
            le snapshot éventuel et les feedbacks. Il alimente directement les jeux d&apos;évaluation FORGE (pertinence,
            couverture, respect de la gouvernance). Les éléments au-delà de votre habilitation restent caviardés et chaque
            export est journalisé dans l&apos;audit.
          </CardDescription>
        </div>
        {isOwner ? (
          <ExportTracesButton slug={slug} days={days} />
        ) : (
          <p className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
            <Lock className="size-3.5" aria-hidden />
            Export réservé aux propriétaires du projet
          </p>
        )}
      </CardHeader>
      <CardContent>
        <pre className="overflow-x-auto rounded-lg border border-border bg-muted/40 p-3 font-mono text-[11.5px] leading-relaxed text-muted-foreground">
          {`{"schema": "orbit.trace.v1",
 "request": {"id": "…", "task": "Rédiger la spécification…", "agent": {"name": "Agent Produit"}, "latency_ms": 640,
             "tokens_used": 3412, "token_budget": 4000, "snapshot": {"name": "spec-atlas", "version": 3}},
 "timings": {"retrieve": 212, "rerank": 38, "total": 640}, "context": "## Décisions en vigueur …",
 "decisions": [{"citation": "S1", "included": true, "reason_code": "INCLUDED_RELEVANT", "scores": {"final": 0.82}},
               {"included": false, "reason_code": "EXCLUDED_SUPERSEDED", "reason_detail": "remplacé par …", "redacted": false}],
 "feedback": [{"rating": 5, "item_flags": []}]}`}
        </pre>
      </CardContent>
    </Card>
  );
}

/** Observability: KPIs, daily series, exclusion/inclusion breakdowns, stage latency, usage, ingestion and request log. */
export function ObservabilityView() {
  const { slug, isOwner } = useCurrentProject();
  const [period, setPeriod] = usePeriodParam();
  const metrics = useMetrics(slug, period);
  const data = metrics.data;
  const loading = metrics.isPending;
  // Keep the previous period on screen (dimmed) while the new one loads, instead of flashing skeletons.
  const refreshing = metrics.isPlaceholderData || (metrics.isFetching && !loading);

  const series = React.useMemo(() => densifySeries(data?.series ?? [], period), [data?.series, period]);
  const reasonRows = React.useMemo(() => buildReasonRows(data?.exclusions_by_reason), [data?.exclusions_by_reason]);
  const inclusionSlices = React.useMemo(
    () => buildInclusionSlices(data?.inclusions_by_type),
    [data?.inclusions_by_type],
  );
  const stageRows = React.useMemo(() => buildStageRows(data?.stage_latency_avg), [data?.stage_latency_avg]);
  const totals = data?.totals;
  const requests = totals?.requests ?? 0;

  const header = (
    <PageHeader
      icon={<Activity />}
      title="Observabilité"
      description="Latence, volume de tokens, coût estimé, motifs d'exclusion et traces des contextes servis aux agents."
      className="pb-0"
      actions={
        <>
          {refreshing ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              Actualisation…
            </span>
          ) : null}
          <SegmentedControl<`${PeriodDays}`>
            value={`${period}`}
            onValueChange={(v) => setPeriod(parsePeriod(v))}
            aria-label="Période analysée"
            options={PERIOD_OPTIONS.map((d) => ({ value: `${d}` as `${PeriodDays}`, label: `${d} jours` }))}
          />
          {isOwner ? <ExportTracesButton slug={slug} days={period} /> : null}
        </>
      }
    />
  );

  if (metrics.isError && !data) {
    return (
      <div className="grid grid-cols-1 gap-6">
        {header}
        <ErrorState
          error={metrics.error}
          title="Impossible de charger les métriques"
          onRetry={() => void metrics.refetch()}
        />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6">
      {header}

      {!loading && requests === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-start gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="grid gap-1">
              <p className="text-sm font-semibold text-foreground">Aucune requête de contexte sur les {period} derniers jours</p>
              <p className="text-[13px] text-muted-foreground">
                Les indicateurs se rempliront dès qu&apos;un agent (API ou MCP) ou l&apos;explorateur assemblera un contexte.
              </p>
            </div>
            <Button asChild variant="secondary" size="sm">
              <Link href={`/projects/${encodeURIComponent(slug)}/explorer`}>
                <Telescope aria-hidden />
                Ouvrir l&apos;explorateur
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div
        className={cn("grid grid-cols-1 gap-4 transition-opacity duration-200", refreshing && "opacity-60")}
        aria-busy={loading || refreshing || undefined}
      >
        <KpiGrid totals={totals} series={series} days={period} loading={loading} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <RequestsChart data={series} loading={loading} total={requests} />
          <LatencyChart
            data={series}
            loading={loading}
            p50={requests > 0 ? (totals?.p50_latency_ms ?? null) : null}
            p95={requests > 0 ? (totals?.p95_latency_ms ?? null) : null}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="grid min-w-0 lg:col-span-2">
            <TokensChart
              data={series}
              loading={loading}
              total={totals?.tokens ?? 0}
              cost={totals?.cost_estimate ?? 0}
            />
          </div>
          <InclusionsChart slices={inclusionSlices} loading={loading} />
        </div>

        {!loading ? <DailyTable data={series} /> : null}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ExclusionsChart rows={reasonRows} loading={loading} />
          <StageLatencyChart rows={stageRows} loading={loading} />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <AgentsTable rows={data?.by_agent ?? []} loading={loading} />
          <TopSourcesTable rows={data?.top_sources ?? []} slug={slug} loading={loading} />
        </div>

        <IngestionStats ingestion={data?.ingestion} loading={loading} />

        <CacheStats cache={data?.cache} loading={loading} />

        {metrics.isError && data ? (
          <p className="text-xs text-muted-foreground" role="status">
            Dernière actualisation impossible ({errorMessage(metrics.error)}) : les données affichées peuvent être
            anciennes.
          </p>
        ) : null}
      </div>

      <RequestLog slug={slug} />

      <ForgeNote slug={slug} days={period} isOwner={isOwner} />

      <p className="text-center text-[11.5px] text-subtle-foreground">
        Agrégats calculés depuis le référentiel ORBIT · {formatNumber(period, 0)} derniers jours (UTC) · métriques
        Prometheus sur <code className="font-mono">/metrics</code> et traces OpenTelemetry si un collecteur OTLP est
        configuré.
      </p>
    </div>
  );
}
