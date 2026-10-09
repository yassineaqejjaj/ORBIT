"use client";

import * as React from "react";
import Link from "next/link";
import { LayoutDashboard, Telescope } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { RoleBadge } from "@/components/domain/enum-badge";
import { projectHref } from "@/components/layout/nav";
import { AddContentMenu } from "@/components/sources/add-content-menu";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useMembers, useProjectOverview } from "@/lib/api/hooks";
import { plural } from "@/lib/format";
import { ActiveDecisions } from "./active-decisions";
import { AttentionList } from "./attention-list";
import { ConnectSourcesCta } from "./connect-sources-cta";
import { IngestionHealth } from "./ingestion-health";
import { MemorySummary } from "./memory-summary";
import { OrbitFlow } from "./orbit-flow";
import { ProjectHealthCard } from "./project-health-card";
import { RecentActivity } from "./recent-activity";
import { SinceLastVisit } from "./since-last-visit";
import { SourceDistribution } from "./source-distribution";

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
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-12" aria-busy="true" aria-label="Chargement de la vue d’ensemble">
      <CardSkeleton className="md:col-span-2 lg:col-span-12" lines={1} />
      <CardSkeleton className="md:col-span-2 lg:col-span-12" lines={2} />
      <CardSkeleton className="lg:col-span-7" lines={6} />
      <CardSkeleton className="lg:col-span-5" lines={4} />
    </div>
  );
}

/**
 * Vue d'ensemble — steering view, organised by importance:
 * 1. state + actions (health, to-do), 2. knowledge (ORBIT flow, decisions, ingestion, memory), 3. metrics + activity.
 * Technical analysis (requests, latency, tokens, cost, exclusion reasons, traces) stays in Observabilité.
 */
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
    <div className="grid grid-cols-1 gap-5">
      <PageHeader
        eyebrow="Vue d’ensemble"
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
                Assembler un contexte
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
              compact
              message={`${plural(data.stats.restricted_documents, "document concerné", "documents concernés")} (C2 ou C3).`}
            />
          ) : null}

          {data.stats.documents === 0 ? <ConnectSourcesCta slug={slug} isOwner={isOwner} /> : null}

          <ProjectHealthCard overview={data} />
          <OrbitFlow slug={slug} overview={data} />

          {/* Two independent columns (no shared rows → no dead space). Below lg, `contents` flattens them and `order-*` restores
              the priority order: to-do, decisions, ingestion, memory, sources, activity, last visit. */}
          <div className="flex flex-col gap-4 lg:grid lg:grid-cols-12 lg:items-start">
            <div className="contents lg:col-span-7 lg:flex lg:flex-col lg:gap-4">
              <ActiveDecisions slug={slug} decisions={data.latest_decisions} className="order-2 lg:order-none" />
              <MemorySummary slug={slug} overview={data} className="order-4 lg:order-none" />
              <RecentActivity slug={slug} events={data.recent_activity} members={members.data} className="order-6 lg:order-none" />
            </div>
            <div className="contents lg:col-span-5 lg:flex lg:flex-col lg:gap-4">
              <AttentionList slug={slug} alerts={data.alerts} className="order-1 lg:order-none" />
              <IngestionHealth slug={slug} ingestion={data.ingestion} stats={data.stats} className="order-3 lg:order-none" />
              <SourceDistribution slug={slug} byKind={data.sources_by_kind} className="order-5 lg:order-none" />
              <SinceLastVisit slug={slug} className="order-7 lg:order-none" />
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
