"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowDownRight, ArrowRight, ArrowUpRight, CheckCircle2, ClipboardPlus, SearchX, Users } from "lucide-react";

import { RelativeTime } from "@/components/domain/relative-time";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useKnowledgeGaps, useRequestGapDocumentation } from "@/lib/api/hooks";
import type { KnowledgeGap } from "@/lib/api/types";
import { plural } from "@/lib/format";

const SEVERITY: Record<KnowledgeGap["severity"], { label: string; tone: "danger" | "warning" | "neutral" }> = {
  critical: { label: "Critique", tone: "danger" },
  recurring: { label: "Récurrente", tone: "warning" },
  isolated: { label: "Isolée", tone: "neutral" },
};

const TREND: Record<KnowledgeGap["trend"], { label: string; icon: React.ReactNode }> = {
  rising: { label: "en hausse", icon: <ArrowUpRight className="size-3.5" aria-hidden /> },
  steady: { label: "stable", icon: <ArrowRight className="size-3.5" aria-hidden /> },
  fading: { label: "en baisse", icon: <ArrowDownRight className="size-3.5" aria-hidden /> },
};

const WINDOWS = [7, 30, 90] as const;

function GapCard({ gap, slug }: { gap: KnowledgeGap; slug: string }) {
  const request = useRequestGapDocumentation(slug);
  const severity = SEVERITY[gap.severity];
  const trend = TREND[gap.trend];
  const done = gap.requested || request.isSuccess;
  return (
    <article className="grid gap-2 rounded-xl border border-border bg-surface p-4 shadow-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={severity.tone}>{severity.label}</Badge>
        <h2 className="text-base font-medium">{gap.topic}</h2>
      </div>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
        <span>
          {plural(gap.requests, "demande", "demandes")} · {plural(gap.askers, "demandeur", "demandeurs")}
        </span>
        <span className="inline-flex items-center gap-1">
          {trend.icon} {trend.label}
        </span>
        <span>
          dernière fois <RelativeTime date={gap.last_seen} />
        </span>
      </p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Users className="size-4 text-muted-foreground" aria-hidden />
        {gap.contributors.length ? (
          <>
            <span className="text-muted-foreground">À solliciter :</span>
            {gap.contributors.map((c) => (
              <Badge key={c.user_id} tone="neutral" title={`${plural(c.items, "élément proche", "éléments proches")}`}>
                {c.label}
              </Badge>
            ))}
          </>
        ) : (
          <span className="text-muted-foreground">Aucune personne identifiée dans la mémoire que vous pouvez consulter.</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {done ? (
          <>
            <Badge tone="success" icon={<CheckCircle2 />}>
              Demande ouverte
            </Badge>
            <Link className="text-sm text-brand hover:underline" href={projectHref(slug, "inbox")}>
              Voir dans la revue mémoire
            </Link>
          </>
        ) : (
          <Button size="sm" variant="secondary" disabled={request.isPending} onClick={() => request.mutate(gap.topic)}>
            <ClipboardPlus aria-hidden /> Demander à documenter
          </Button>
        )}
      </div>
    </article>
  );
}

export function KnowledgeGapsView() {
  const { slug } = useCurrentProject();
  const [days, setDays] = React.useState<(typeof WINDOWS)[number]>(30);
  const gaps = useKnowledgeGaps(slug, days);
  return (
    <div className="grid gap-5">
      <PageHeader
        icon={<SearchX />}
        title="Lacunes de connaissance"
        description="Les sujets que le contexte servi aux agents et aux personnes ne couvre pas, encore et encore. Seul le sujet est affiché, jamais la question posée."
      >
        <div className="flex flex-wrap gap-2" role="group" aria-label="Période">
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              aria-pressed={days === w}
              onClick={() => setDays(w)}
              className={`rounded-full border px-3 py-1 text-sm ${days === w ? "border-brand bg-brand/10" : "border-border hover:border-border-strong"}`}
            >
              {w} jours
            </button>
          ))}
        </div>
      </PageHeader>
      {gaps.isLoading ? <Skeleton className="h-64 rounded-xl" /> : null}
      {gaps.isError ? <ErrorState error={gaps.error} onRetry={() => gaps.refetch()} /> : null}
      {gaps.data && gaps.data.gaps.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 />}
          title="Aucune lacune récurrente"
          description={`Sur ${plural(gaps.data.analysed_requests, "demande analysée", "demandes analysées")}, rien ne manque à la mémoire sur cette période.`}
        />
      ) : null}
      {gaps.data?.gaps.map((gap) => <GapCard key={gap.key} gap={gap} slug={slug} />)}
    </div>
  );
}
