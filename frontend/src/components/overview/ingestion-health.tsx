"use client";

import Link from "next/link";
import { ArrowRight, Workflow } from "lucide-react";

import { RelativeTime } from "@/components/domain/relative-time";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useSources } from "@/lib/api/hooks";
import type { OverviewIngestion, OverviewStats } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Level 2 — ingestion health. Compact when everything is fine; expanded and highlighted on incident
 * (failed jobs) or while documents are being processed.
 */
export function IngestionHealth({
  slug,
  ingestion,
  stats,
  className,
}: {
  slug: string;
  ingestion: OverviewIngestion;
  stats: OverviewStats;
  className?: string;
}) {
  const sources = useSources(slug);
  const lastIngestedAt = (sources.data ?? [])
    .map((s) => s.last_ingested_at)
    .filter((d): d is string => Boolean(d))
    .sort()
    .at(-1);
  const jobsHref = `${projectHref(slug, "sources")}?tab=jobs`;
  const active = ingestion.queued + ingestion.running;
  const incident = ingestion.failed > 0;
  const indexedRatio = stats.documents > 0 ? stats.documents_indexed / stats.documents : null;
  const status = incident
    ? { label: "Incident", tone: "red" as const, pulse: false }
    : active > 0
      ? { label: "En cours", tone: "blue" as const, pulse: true }
      : { label: "Opérationnel", tone: "green" as const, pulse: false };

  return (
    <Card className={cn("flex flex-col", incident && "border-danger/40 ring-1 ring-danger/20", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Workflow className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Santé de l&apos;ingestion</CardTitle>
        <CardAction>
          <Badge tone={status.tone} dot={!status.pulse} pulse={status.pulse}>
            {status.label}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="grid flex-1 content-start gap-3">
        <p className="text-[13px] text-foreground">
          <span className="text-lg font-semibold tabular-nums">{formatNumber(stats.documents_indexed, 0)}</span>
          <span className="text-muted-foreground"> / {formatNumber(stats.documents, 0)} documents indexés</span>
        </p>
        {incident || active > 0 ? (
          <Progress
            value={active > 0 && !incident ? null : indexedRatio === null ? 0 : indexedRatio * 100}
            tone={incident ? "amber" : "blue"}
            size="sm"
            aria-label={active > 0 ? "Ingestion en cours" : "Part des documents indexés"}
          />
        ) : null}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <div className="flex items-baseline gap-1">
            <span className="font-semibold tabular-nums text-foreground">{formatNumber(ingestion.succeeded_24h, 0)}</span>
            <span>réussis (24 h)</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="font-semibold tabular-nums text-foreground">{formatNumber(active, 0)}</span>
            {/* Live activity shimmer only while jobs run (disabled under reduced motion). */}
            <span className={cn(active > 0 && "text-shimmer")}>en cours</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className={cn("font-semibold tabular-nums", incident ? "text-danger" : "text-foreground")}>
              {formatNumber(ingestion.failed, 0)}
            </span>
            <span>en échec</span>
          </div>
        </div>
        {lastIngestedAt ? (
          <p className="text-xs text-muted-foreground">
            Dernière ingestion : <RelativeTime date={lastIngestedAt} />
          </p>
        ) : null}
      </CardContent>
      <div className="border-t border-border px-5 py-3">
        <Link
          href={incident ? `${jobsHref}&job_status=failed` : jobsHref}
          className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {incident ? "Voir les traitements en échec" : "Voir les traitements"}
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </div>
    </Card>
  );
}
