"use client";

import * as React from "react";
import { CircleAlert, ListChecks, Timer } from "lucide-react";

import { JobKindBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { StatusBadge } from "@/components/domain/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import type { Job } from "@/lib/api/types";
import { formatDateTime, formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { JobStepsTimeline, jobDurationMs } from "./job-steps";

/** "Traitement" tab: every job run on this document, newest first, each with its timed step timeline. */
export function DocumentProcessing({ jobs }: { jobs: readonly Job[] }) {
  const sorted = React.useMemo(
    () => [...jobs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [jobs],
  );
  if (sorted.length === 0) {
    return (
      <EmptyState
        icon={<ListChecks />}
        title="Aucun traitement"
        description="Les traitements (ingestion, réindexation, oubli) de ce document et leurs étapes chronométrées apparaîtront ici."
      />
    );
  }
  return (
    <div className="grid gap-3">
      {sorted.map((job, index) => {
        const duration = jobDurationMs(job);
        return (
          <Card key={job.id} className={cn(index > 0 && "bg-card/70")}>
            <CardHeader className="flex-row flex-wrap items-center gap-2 pb-3">
              <JobKindBadge value={job.kind} size="md" />
              <StatusBadge kind="job" status={job.status} size="md" />
              {index === 0 ? (
                <Badge tone="neutral" variant="outline">
                  Dernier traitement
                </Badge>
              ) : null}
              {job.attempts > 1 ? (
                <Badge tone="amber" variant="outline">
                  {job.attempts} tentatives
                </Badge>
              ) : null}
              <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
                {duration !== null ? (
                  <span className="inline-flex items-center gap-1 font-medium tabular-nums text-foreground">
                    <Timer className="size-3.5 text-muted-foreground" aria-hidden />
                    {formatMs(duration)}
                  </span>
                ) : null}
                <span title={formatDateTime(job.created_at)}>
                  <RelativeTime date={job.created_at} />
                </span>
              </span>
            </CardHeader>
            <CardContent className="grid gap-3">
              <JobStepsTimeline job={job} />
              {job.error ? (
                <p className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900 dark:border-red-400/30 dark:bg-red-400/10 dark:text-red-100">
                  <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                  <span className="break-words">{job.error}</span>
                </p>
              ) : null}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
