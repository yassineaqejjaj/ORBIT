"use client";

import * as React from "react";
import Link from "next/link";
import { Bot, Camera, Cpu, Fingerprint, RotateCcw, Timer, UserRound } from "lucide-react";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { IntentBadge } from "@/components/domain/enum-badge";
import { TokenMeter } from "@/components/domain/token-meter";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/code-block";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { ContextPackage } from "@/lib/api/types";
import { maxItemClassification } from "@/lib/explorer-utils";
import { formatDateTime, formatMs, formatNumber, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ResultActor {
  /** "Agent Produit" or "Moi (humain)". */
  label: string;
  isAgent: boolean;
  onBehalfOf?: string | null;
}

export interface ResultSummaryProps {
  pkg: ContextPackage;
  slug: string;
  actor?: ResultActor | null;
  onReuse?: () => void;
}

function Metric({
  label,
  value,
  hint,
  className,
  valueClassName,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  className?: string;
  valueClassName?: string;
}) {
  return (
    <div className={cn("grid content-start gap-1 bg-card px-4 py-3", className)}>
      <dt className="text-[11.5px] font-medium text-muted-foreground">{label}</dt>
      <dd className={cn("text-xl font-semibold tracking-tight tabular-nums text-foreground", valueClassName)}>{value}</dd>
      {hint ? <dd className="text-[11.5px] text-subtle-foreground">{hint}</dd> : null}
    </div>
  );
}

const CLASSIFICATION_WARNING = /classifi|C2|C3|confidentiel|secret/i;

const RETRIEVAL_LABELS: Record<string, string> = {
  "hybrid-bm25-knn-rrf-v1": "hybride BM25 + k-NN · RRF (v1)",
};

/** Headline of an assembled context: budget, counts, latency, snapshot, configuration, trace and warnings. */
export function ResultSummary({ pkg, slug, actor, onReuse }: ResultSummaryProps) {
  const maxLevel = maxItemClassification(pkg.items);
  const excludedCount = Object.values(pkg.exclusion_summary).reduce((acc, n) => acc + (typeof n === "number" ? n : 0), 0) || pkg.excluded.length;
  const otherWarnings = pkg.warnings.filter((w) => !(maxLevel >= 2 && CLASSIFICATION_WARNING.test(w)));
  const snapshotHref = pkg.snapshot
    ? `/projects/${encodeURIComponent(slug)}/snapshots/${encodeURIComponent(pkg.snapshot.name)}`
    : null;

  return (
    <div className="grid gap-3">
      <section className="overflow-hidden rounded-xl border border-border bg-card shadow-xs" aria-label="Synthèse du contexte assemblé">
        <div className="flex flex-col gap-3 border-b border-border px-4 py-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="grid min-w-0 gap-1.5">
            <p className="text-[15px] font-semibold leading-snug text-foreground">{pkg.task}</p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
              <IntentBadge value={pkg.intent} />
              {actor ? (
                <span className="inline-flex items-center gap-1">
                  {actor.isAgent ? <Bot className="size-3.5" aria-hidden /> : <UserRound className="size-3.5" aria-hidden />}
                  <span className="font-medium text-foreground">{actor.label}</span>
                  {actor.onBehalfOf ? <span>pour {actor.onBehalfOf}</span> : null}
                </span>
              ) : null}
              <span className="tabular-nums">{formatDateTime(pkg.created_at)}</span>
              {pkg.snapshot && snapshotHref ? (
                <Link href={snapshotHref} className="inline-flex">
                  <Badge tone="violet" icon={<Camera aria-hidden />} className="hover:underline">
                    Snapshot {pkg.snapshot.name} · v{pkg.snapshot.version}
                  </Badge>
                </Link>
              ) : null}
            </div>
          </div>
          {onReuse ? (
            <Button variant="secondary" size="sm" onClick={onReuse} leftIcon={<RotateCcw aria-hidden />} className="self-start">
              Réutiliser cette tâche
            </Button>
          ) : null}
        </div>

        <dl className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4 lg:grid-cols-6">
          <div className="col-span-2 grid content-start gap-2 bg-card px-4 py-3 sm:col-span-4 lg:col-span-2">
            <dt className="text-[11.5px] font-medium text-muted-foreground">Budget de tokens</dt>
            <dd>
              <TokenMeter used={pkg.tokens_used} budget={pkg.token_budget} size="md" />
            </dd>
          </div>
          <Metric label="Candidats" value={formatNumber(pkg.candidates_count, 0)} hint="sources, mémoire, session" />
          <Metric
            label="Retenus"
            value={formatNumber(pkg.items.length, 0)}
            valueClassName="text-primary"
            hint={pkg.items.some((i) => i.reason_code === "INCLUDED_PINNED") ? "dont hérités du snapshot" : "cités [S1]…"}
          />
          <Metric label="Exclus" value={formatNumber(excludedCount, 0)} hint="avec motif explicite" />
          <Metric
            label="Latence totale"
            value={
              <span className="inline-flex items-center gap-1.5">
                <Timer className="size-4 text-subtle-foreground" aria-hidden />
                {formatMs(pkg.timings.total)}
              </span>
            }
            hint={pkg.timings.total <= 1500 ? "objectif p95 < 1,5 s tenu" : "au-delà de l'objectif p95 1,5 s"}
          />
        </dl>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border bg-muted/30 px-4 py-2 text-[11.5px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Cpu className="size-3.5" aria-hidden />
            <span>
              Recherche{" "}
              <span className="font-medium text-foreground">{RETRIEVAL_LABELS[pkg.config.retrieval] ?? pkg.config.retrieval}</span>
            </span>
          </span>
          <span>
            Reranker <span className="font-medium text-foreground">{pkg.config.reranker}</span>
          </span>
          <SimpleTooltip content={pkg.config.embedding_model}>
            <span className="max-w-72 truncate">
              Embeddings <span className="font-medium text-foreground">{pkg.config.embedding_model.split("/").pop()}</span>
            </span>
          </SimpleTooltip>
          <span>
            LLM <span className="font-medium text-foreground">{pkg.config.llm ?? "aucun (mode déterministe)"}</span>
          </span>
          <span className="inline-flex items-center gap-1 sm:ml-auto">
            <Fingerprint className="size-3.5" aria-hidden />
            Trace
            <SimpleTooltip content={pkg.trace_id}>
              <code className="rounded bg-muted px-1 font-mono text-[11px] text-foreground">{shortId(pkg.trace_id)}</code>
            </SimpleTooltip>
            <CopyButton value={pkg.trace_id} label="Copier l'identifiant de trace" className="size-6" />
          </span>
        </div>
      </section>

      <ClassificationBanner level={maxLevel} context="serve" />
      {otherWarnings.length > 0 ? (
        <Alert tone="amber" title={otherWarnings.length > 1 ? "Avertissements" : "Avertissement"}>
          {otherWarnings.length > 1 ? (
            <ul className="list-disc space-y-0.5 pl-4">
              {otherWarnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : (
            otherWarnings[0]
          )}
        </Alert>
      ) : null}
    </div>
  );
}
