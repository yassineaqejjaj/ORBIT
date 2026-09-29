"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Workflow } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { OverviewIngestion, OverviewStats } from "@/lib/api/types";
import type { Tone } from "@/lib/enums";
import { formatNumber, formatPercent } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

interface Cell {
  key: keyof OverviewIngestion;
  label: string;
  tone: Tone;
  href: string;
}

export function IngestionHealthCard({
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
  const jobsHref = `${projectHref(slug, "sources")}?tab=jobs`;
  const cells: Cell[] = [
    { key: "queued", label: "En file", tone: "neutral", href: `${jobsHref}&job_status=queued` },
    { key: "running", label: "En cours", tone: "blue", href: `${jobsHref}&job_status=running` },
    { key: "failed", label: "En échec", tone: "red", href: `${jobsHref}&job_status=failed` },
    { key: "succeeded_24h", label: "Réussis (24 h)", tone: "green", href: `${jobsHref}&job_status=succeeded` },
  ];
  const active = ingestion.queued + ingestion.running;
  const indexedRatio = stats.documents > 0 ? stats.documents_indexed / stats.documents : null;
  const status: { label: string; tone: Tone; pulse: boolean } =
    ingestion.failed > 0
      ? { label: "Attention requise", tone: "red", pulse: false }
      : active > 0
        ? { label: "Ingestion en cours", tone: "blue", pulse: true }
        : { label: "Pipeline au repos", tone: "green", pulse: false };

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center gap-2">
        <Workflow className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Santé de l&apos;ingestion</CardTitle>
        <CardAction>
          <Badge tone={status.tone} dot={!status.pulse} pulse={status.pulse}>
            {status.label}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="grid flex-1 content-start gap-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {cells.map((cell) => {
            const value = ingestion[cell.key];
            const t = toneClasses(cell.tone);
            return (
              <Link
                key={cell.key}
                href={cell.href}
                className="group grid gap-1 rounded-lg border border-border bg-background px-3 py-2.5 transition-colors hover:border-border-strong hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className={cn("size-1.5 rounded-full", t.dot)} aria-hidden />
                  {cell.label}
                </span>
                <span
                  className={cn(
                    "text-xl font-semibold tabular-nums tracking-tight",
                    cell.key === "failed" && value > 0 ? t.text : "text-foreground",
                  )}
                >
                  {formatNumber(value, 0)}
                </span>
              </Link>
            );
          })}
        </div>
        <div className="grid gap-1.5">
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="text-muted-foreground">Documents indexés</span>
            <span className="tabular-nums text-foreground">
              <span className="font-semibold">{formatNumber(stats.documents_indexed, 0)}</span>
              <span className="text-muted-foreground"> / {formatNumber(stats.documents, 0)}</span>
              {indexedRatio !== null ? (
                <span className="ml-1.5 font-medium text-muted-foreground">{formatPercent(indexedRatio)}</span>
              ) : null}
            </span>
          </div>
          <Progress
            value={indexedRatio === null ? 0 : indexedRatio * 100}
            tone={ingestion.failed > 0 ? "amber" : "teal"}
            size="md"
            aria-label="Part des documents indexés"
          />
          {active > 0 ? (
            <div className="grid gap-1.5 pt-1">
              <span className="text-xs text-muted-foreground">
                {formatNumber(active, 0)} traitement{active > 1 ? "s" : ""} en attente ou en cours
              </span>
              <Progress value={null} tone="blue" size="xs" aria-label="Ingestion en cours" />
            </div>
          ) : null}
        </div>
        <dl className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-xs">
          <div className="grid gap-0.5">
            <dt className="text-muted-foreground">Extraits</dt>
            <dd className="font-medium tabular-nums text-foreground">{formatNumber(stats.chunks, 0)}</dd>
          </div>
          <div className="grid gap-0.5">
            <dt className="text-muted-foreground">Avec données perso.</dt>
            <dd className="font-medium tabular-nums text-foreground">{formatNumber(stats.pii_documents, 0)}</dd>
          </div>
          <div className="grid gap-0.5">
            <dt className="text-muted-foreground">Classifiés C2+</dt>
            <dd
              className={cn(
                "font-medium tabular-nums",
                stats.restricted_documents > 0 ? "text-amber-700 dark:text-amber-300" : "text-foreground",
              )}
            >
              {formatNumber(stats.restricted_documents, 0)}
            </dd>
          </div>
        </dl>
      </CardContent>
      <CardFooter>
        <Link
          href={jobsHref}
          className="inline-flex items-center gap-1 rounded font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Voir tous les traitements
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </CardFooter>
    </Card>
  );
}
