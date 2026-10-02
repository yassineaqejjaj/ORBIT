"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, History, LayoutDashboard, Telescope } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { RoleBadge } from "@/components/domain/enum-badge";
import { projectHref } from "@/components/layout/nav";
import { AddContentMenu } from "@/components/sources/add-content-menu";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useMembers, useProjectOverview } from "@/lib/api/hooks";
import { formatNumber, plural } from "@/lib/format";
import { ActivityTimeline } from "./activity-timeline";
import { AlertsCard } from "./alerts-card";
import { ConnectSourcesCta } from "./connect-sources-cta";
import { IngestionHealthCard } from "./ingestion-health-card";
import { LatestDecisionsCard } from "./latest-decisions-card";
import { MemoryBreakdownCard } from "./memory-breakdown-card";
import { OverviewKpis, OverviewKpisSkeleton } from "./overview-kpis";
import { SourcesByKindCard } from "./sources-by-kind-card";

const ACTIVE_POLL_MS = 5_000;
const IDLE_POLL_MS = 60_000;

function CardSkeleton({ className, lines = 4 }: { className?: string; lines?: number }) {
  return (
    <Card className={className}>
      <CardHeader>
        <Skeleton className="h-4 w-40" />
      </CardHeader>
      <CardContent>
        <SkeletonText lines={lines} />
      </CardContent>
    </Card>
  );
}

function OverviewSkeleton() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-label="Chargement de la vue projet">
      <OverviewKpisSkeleton />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <CardSkeleton className="lg:col-span-5" />
        <CardSkeleton className="lg:col-span-7" />
        <Card className="lg:col-span-7">
          <CardHeader>
            <Skeleton className="h-4 w-40" />
          </CardHeader>
          <CardContent className="grid gap-6 md:grid-cols-2">
            <Skeleton className="mx-auto size-40 rounded-full" />
            <SkeletonText lines={5} />
          </CardContent>
        </Card>
        <CardSkeleton className="lg:col-span-5" lines={6} />
        <CardSkeleton className="lg:col-span-7" lines={8} />
        <CardSkeleton className="lg:col-span-5" lines={8} />
      </div>
    </div>
  );
}

/** Project overview (Vue projet): KPIs, alerts, ingestion health, memory, sources, decisions and activity. */
export function OverviewView() {
  const { project, slug, role, isOwner } = useCurrentProject();
  const overview = useProjectOverview(slug, {
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      return data.ingestion.queued + data.ingestion.running > 0 ? ACTIVE_POLL_MS : IDLE_POLL_MS;
    },
  });
  const members = useMembers(slug);
  const data = overview.data;

  return (
    <div className="grid grid-cols-1 gap-6">
      <PageHeader
        eyebrow="Vue projet"
        icon={<LayoutDashboard />}
        title={project.name}
        meta={<RoleBadge value={role} size="md" />}
        description={
          project.description?.trim() ||
          "Sources, mémoire et contextes servis aux agents IA de ce projet, avec leur gouvernance."
        }
        actions={
          <>
            <Button asChild variant="secondary">
              <Link href={projectHref(slug, "explorer")}>
                <Telescope aria-hidden />
                Explorer le contexte
              </Link>
            </Button>
            <RequireRole min="editor">
              <AddContentMenu slug={slug} label="Ingérer" />
            </RequireRole>
          </>
        }
      />

      {overview.isPending ? (
        <OverviewSkeleton />
      ) : overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => void overview.refetch()} size="lg" />
      ) : data ? (
        <>
          {data.stats.restricted_documents > 0 ? (
            <ClassificationBanner
              level={2}
              context="project"
              message={`${plural(data.stats.restricted_documents, "document classifié", "documents classifiés")} C2 ou C3 : servis uniquement aux personnes et agents dont l'habilitation le permet.`}
            />
          ) : null}

          {data.stats.documents === 0 ? <ConnectSourcesCta slug={slug} isOwner={isOwner} /> : null}

          <OverviewKpis slug={slug} overview={data} />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <AlertsCard slug={slug} alerts={data.alerts} className="lg:col-span-5" />
            <IngestionHealthCard slug={slug} ingestion={data.ingestion} stats={data.stats} className="lg:col-span-7" />
            <MemoryBreakdownCard slug={slug} overview={data} className="lg:col-span-7" />
            <SourcesByKindCard slug={slug} byKind={data.sources_by_kind} className="lg:col-span-5" />
            <LatestDecisionsCard slug={slug} decisions={data.latest_decisions} className="lg:col-span-7" />
            <Card className="flex flex-col lg:col-span-5">
              <CardHeader className="flex-row items-center gap-2">
                <History className="size-4 text-muted-foreground" aria-hidden />
                <CardTitle>Activité récente</CardTitle>
                <CardAction>
                  <Link
                    href={`${projectHref(slug, "settings")}?tab=audit`}
                    className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Journal d&apos;audit
                    <ArrowRight className="size-3" aria-hidden />
                  </Link>
                </CardAction>
              </CardHeader>
              <CardContent className="flex-1">
                <ActivityTimeline slug={slug} events={data.recent_activity} members={members.data} />
              </CardContent>
            </Card>
          </div>

          <p className="text-center text-xs text-muted-foreground">
            {formatNumber(data.stats.snapshots, 0)} snapshot{data.stats.snapshots > 1 ? "s" : ""} de contexte ·{" "}
            {formatNumber(data.stats.chunks, 0)} extraits indexés · actualisé automatiquement
          </p>
        </>
      ) : null}
    </div>
  );
}
