"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, CircleAlert, ListChecks, RefreshCw } from "lucide-react";

import { JobKindBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { StatusBadge } from "@/components/domain/status-badge";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Pagination } from "@/components/ui/pagination";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useJobs } from "@/lib/api/hooks";
import type { JobWithDocument } from "@/lib/api/types";
import { isEnumValue, JOB_STATUS_META, JOB_STATUSES, type JobStatus } from "@/lib/enums";
import { formatDateTime, formatMs, plural, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { JobStepsInline, JobStepsTimeline, jobDurationMs } from "./job-steps";
import { parsePositiveInt, useUrlParams } from "./use-url-params";

const POLL_MS = 3_000;
const ALL = "all";
const COLUMNS = 8;

type StatusFilter = JobStatus | typeof ALL;

function JobRow({ slug, job }: { slug: string; job: JobWithDocument }) {
  const [open, setOpen] = React.useState(false);
  const duration = jobDurationMs(job);
  const detailsId = `job-${job.id}-details`;
  const toggle = () => setOpen((o) => !o);
  return (
    <>
      <TableRow
        interactive
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("a")) return;
          toggle();
        }}
        className={cn(open && "bg-muted/40")}
      >
        <TableCell className="w-8 pr-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggle();
            }}
            aria-expanded={open}
            aria-controls={detailsId}
            aria-label={open ? "Masquer les étapes" : "Afficher les étapes"}
            className="flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} aria-hidden />
          </button>
        </TableCell>
        <TableCell>
          <JobKindBadge value={job.kind} />
        </TableCell>
        <TableCell className="max-w-72">
          {job.document_id ? (
            <Link
              href={`${projectHref(slug, "sources")}/${encodeURIComponent(job.document_id)}`}
              className="block truncate rounded font-medium text-foreground hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {job.document_title ?? `Document ${shortId(job.document_id)}`}
            </Link>
          ) : (
            <span className="text-muted-foreground">Traitement du projet</span>
          )}
        </TableCell>
        <TableCell>
          <StatusBadge kind="job" status={job.status} />
        </TableCell>
        <TableCell>
          <JobStepsInline job={job} />
        </TableCell>
        <TableCell className="text-right tabular-nums text-muted-foreground">
          {job.attempts > 1 ? (
            <Badge tone="amber" variant="outline" title="Nombre de tentatives">
              {job.attempts} essais
            </Badge>
          ) : (
            job.attempts
          )}
        </TableCell>
        <TableCell className="text-right tabular-nums">{formatMs(duration)}</TableCell>
        <TableCell>
          <span title={formatDateTime(job.created_at)}>
            <RelativeTime date={job.created_at} className="text-muted-foreground" />
          </span>
        </TableCell>
      </TableRow>
      {open ? (
        <tr id={detailsId}>
          <td colSpan={COLUMNS} className="border-b border-border bg-muted/20 px-4 py-4 sm:pl-14">
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
              <JobStepsTimeline job={job} />
              <dl className="grid content-start gap-2 text-xs">
                <div className="grid gap-0.5">
                  <dt className="text-muted-foreground">Créé</dt>
                  <dd className="text-foreground">{formatDateTime(job.created_at)}</dd>
                </div>
                <div className="grid gap-0.5">
                  <dt className="text-muted-foreground">Démarré</dt>
                  <dd className="text-foreground">{formatDateTime(job.started_at)}</dd>
                </div>
                <div className="grid gap-0.5">
                  <dt className="text-muted-foreground">Terminé</dt>
                  <dd className="text-foreground">{formatDateTime(job.finished_at)}</dd>
                </div>
                <div className="grid gap-0.5">
                  <dt className="text-muted-foreground">Identifiant</dt>
                  <dd className="font-mono text-[11px] text-foreground">{job.id}</dd>
                </div>
              </dl>
            </div>
            {job.error ? (
              <p className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900 dark:border-red-400/30 dark:bg-red-400/10 dark:text-red-100">
                <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                <span className="break-words">{job.error}</span>
              </p>
            ) : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}

/** Traitements tab: ingestion/reindex/forget/consolidation jobs with their timed steps. */
export function JobsPanel({ slug }: { slug: string }) {
  const { get, set } = useUrlParams();
  const statusParam = get("job_status");
  const status: StatusFilter = isEnumValue(JOB_STATUSES, statusParam) ? statusParam : ALL;
  const page = parsePositiveInt(get("job_page"));

  const jobs = useJobs(
    slug,
    { status: status === ALL ? undefined : status, page },
    {
      refetchInterval: (query) =>
        query.state.data?.items.some((j) => j.status === "queued" || j.status === "running") ? POLL_MS : false,
    },
  );
  const data = jobs.data;
  const activeCount = data?.items.filter((j) => j.status === "queued" || j.status === "running").length ?? 0;

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl<StatusFilter>
          size="sm"
          value={status}
          onValueChange={(v) => set({ job_status: v === ALL ? null : v, job_page: null })}
          aria-label="Filtrer par statut"
          options={[
            { value: ALL, label: "Tous" },
            ...JOB_STATUSES.map((s) => ({ value: s, label: JOB_STATUS_META[s].label })),
          ]}
        />
        {activeCount > 0 ? (
          <Badge tone="blue" pulse>
            {plural(activeCount, "traitement")} actif{activeCount > 1 ? "s" : ""} · actualisation automatique
          </Badge>
        ) : null}
        {jobs.isFetching && !jobs.isPending ? (
          <RefreshCw className="size-3 animate-spin text-muted-foreground" aria-label="Actualisation" />
        ) : null}
        {data ? <span className="ml-auto text-xs tabular-nums text-muted-foreground">{plural(data.total, "traitement")}</span> : null}
      </div>

      {jobs.isError ? (
        <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />
      ) : !jobs.isPending && data && data.items.length === 0 ? (
        <EmptyState
          icon={<ListChecks />}
          title={status === ALL ? "Aucun traitement" : `Aucun traitement « ${JOB_STATUS_META[status].label.toLowerCase()} »`}
          description="Chaque ingestion, réindexation, oubli ou consolidation crée un traitement dont les étapes sont chronométrées."
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8 pr-0">
                  <span className="sr-only">Détails</span>
                </TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Document</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Étapes</TableHead>
                <TableHead className="text-right">Essais</TableHead>
                <TableHead className="text-right">Durée</TableHead>
                <TableHead>Créé</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.isPending
                ? Array.from({ length: 8 }, (_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: COLUMNS }, (__, j) => (
                        <TableCell key={j}>
                          <Skeleton className={cn("h-3.5", j === 2 ? "w-48" : j === 0 ? "w-4" : "w-16")} />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                : data?.items.map((job) => <JobRow key={job.id} slug={slug} job={job} />)}
            </TableBody>
          </Table>
          {data && data.total > 0 ? (
            <div className="border-t border-border px-4 py-3">
              <Pagination
                page={data.page}
                pageSize={data.page_size || 25}
                total={data.total}
                onPageChange={(p) => set({ job_page: p > 1 ? p : null })}
                disabled={jobs.isFetching}
              />
            </div>
          ) : null}
        </Card>
      )}
    </div>
  );
}
