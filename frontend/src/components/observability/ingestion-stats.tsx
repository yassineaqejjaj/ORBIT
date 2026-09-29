import * as React from "react";
import { DatabaseZap, Gauge } from "lucide-react";

import type { MetricsIngestion } from "@/lib/api/types";
import {
  DOCUMENT_STATUSES,
  DOCUMENT_STATUS_META,
  JOB_STATUSES,
  JOB_STATUS_META,
} from "@/lib/enums";
import { formatMs, formatNumber, formatPercent } from "@/lib/format";
import { buildStatusSegments, type StatusSegment } from "@/lib/observability-utils";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";
import { ChartCard } from "./chart-card";

function Distribution({ title, total, segments, unit }: { title: string; total: number; segments: StatusSegment[]; unit: string }) {
  return (
    <div className="grid content-start gap-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[13px] font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">
          <span className="text-base font-semibold tabular-nums text-foreground">{formatNumber(total, 0)}</span> {unit}
        </p>
      </div>
      {total > 0 ? (
        <>
          <div
            className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full"
            role="img"
            aria-label={`${title} : ${segments.map((s) => `${s.label} ${s.count}`).join(", ")}`}
          >
            {segments.map((s) => (
              <span
                key={s.key}
                className={cn("h-full first:rounded-l-full last:rounded-r-full", toneClasses(s.tone).bar)}
                style={{ width: `${s.ratio * 100}%`, minWidth: 4 }}
                title={`${s.label} : ${formatNumber(s.count, 0)}`}
              />
            ))}
          </div>
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {segments.map((s) => (
              <li key={s.key} className="flex items-center gap-1.5">
                <span className={cn("size-2 shrink-0 rounded-full", toneClasses(s.tone).dot)} aria-hidden />
                <span className="flex-1 truncate text-muted-foreground">{s.label}</span>
                <span className="font-medium tabular-nums text-foreground">{formatNumber(s.count, 0)}</span>
                <span className="w-9 text-right tabular-nums text-subtle-foreground">{formatPercent(s.ratio)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">Aucun élément.</p>
      )}
    </div>
  );
}

/** Ingestion pipeline health: documents by status, jobs by status, average ingestion time. */
export function IngestionStats({ ingestion, loading }: { ingestion: MetricsIngestion | undefined; loading?: boolean }) {
  const docs = React.useMemo(
    () => buildStatusSegments(ingestion?.documents_by_status, DOCUMENT_STATUSES, DOCUMENT_STATUS_META),
    [ingestion?.documents_by_status],
  );
  const jobs = React.useMemo(
    () => buildStatusSegments(ingestion?.jobs_by_status, JOB_STATUSES, JOB_STATUS_META),
    [ingestion?.jobs_by_status],
  );
  return (
    <ChartCard
      title="Ingestion"
      description="État du pipeline (extraction, PII, classification, découpage, vectorisation, indexation)."
      icon={<DatabaseZap aria-hidden />}
      loading={loading}
      height={140}
    >
      <div className="grid gap-6 md:grid-cols-[1fr_1fr_12rem]">
        <Distribution title="Documents par statut" total={docs.total} segments={docs.segments} unit="documents" />
        <Distribution title="Jobs par statut" total={jobs.total} segments={jobs.segments} unit="jobs" />
        <div className="grid content-start gap-1 rounded-lg border border-border bg-muted/30 p-3">
          <p className="flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground">
            <Gauge className="size-3.5" aria-hidden />
            Temps moyen d&apos;ingestion
          </p>
          <p className="text-2xl font-semibold tracking-tight tabular-nums text-foreground">{formatMs(ingestion?.avg_ingest_ms)}</p>
          <p className="text-[11.5px] text-subtle-foreground">par document, de l&apos;extraction à l&apos;indexation</p>
        </div>
      </div>
    </ChartCard>
  );
}
