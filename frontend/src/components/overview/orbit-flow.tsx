"use client";

import Link from "next/link";
import { Brain, ChevronRight, CircleCheck, Database, FileText, Gavel, Send, TriangleAlert } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Card, CardContent } from "@/components/ui/card";
import type { Overview } from "@/lib/api/types";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

interface FlowStep {
  key: string;
  label: string;
  value: number;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  href: string;
  /** Short status under the value; `warn` turns it amber (icon + text, never color alone). */
  status: { ok: boolean; text: string };
}

/**
 * The ORBIT cycle at a glance: sources → documents → memory → decisions → contexts served.
 * It doubles as the business KPI row (memory to validate, decisions in force, contexts served).
 */
export function OrbitFlow({ slug, overview, className }: { slug: string; overview: Overview; className?: string }) {
  const { stats, ingestion, memory_by_status: byStatus, context } = overview;
  const notIndexed = Math.max(0, stats.documents - stats.documents_indexed);
  const proposed = byStatus.proposed ?? 0;
  const steps: FlowStep[] = [
    {
      key: "sources",
      label: "Sources",
      value: stats.sources,
      icon: Database,
      href: `${projectHref(slug, "sources")}?tab=sources`,
      status: stats.sources > 0 ? { ok: true, text: "connectées" } : { ok: false, text: "aucune source" },
    },
    {
      key: "documents",
      label: "Documents",
      value: stats.documents_indexed,
      icon: FileText,
      href: projectHref(slug, "sources"),
      status:
        ingestion.failed > 0
          ? { ok: false, text: `${ingestion.failed} en échec` }
          : notIndexed > 0
            ? { ok: false, text: `${notIndexed} en attente` }
            : { ok: true, text: "tous indexés" },
    },
    {
      key: "memory",
      label: "Mémoires",
      value: stats.memory_items,
      icon: Brain,
      href: projectHref(slug, "memory"),
      status: proposed > 0 ? { ok: false, text: `${formatNumber(proposed, 0)} à valider` } : { ok: true, text: "à jour" },
    },
    {
      key: "decisions",
      label: "Décisions",
      value: stats.validated_decisions,
      icon: Gavel,
      href: `${projectHref(slug, "memory")}?kind=decision&status=validated`,
      status: stats.validated_decisions > 0 ? { ok: true, text: "en vigueur" } : { ok: false, text: "aucune validée" },
    },
    {
      key: "contexts",
      label: "Contextes",
      value: context.requests_7d,
      icon: Send,
      href: projectHref(slug, "observability"),
      status: context.requests_7d > 0 ? { ok: true, text: "servis sur 7 j" } : { ok: false, text: "aucun sur 7 j" },
    },
  ];

  return (
    <Card className={className}>
      <CardContent className="grid gap-4 py-4">
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:flex lg:items-stretch lg:gap-0" aria-label="Cycle ORBIT">
          {steps.map((step, index) => {
            const Icon = step.icon;
            return (
              <li key={step.key} className="flex min-w-0 items-center lg:flex-1">
                <Link
                  href={step.href}
                  className="group grid w-full min-w-0 gap-1 rounded-lg px-3 py-2.5 transition-colors duration-150 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                >
                  <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <Icon className="size-3.5 text-brand" aria-hidden />
                    {step.label}
                  </span>
                  <span className="text-2xl font-semibold tabular-nums tracking-tight text-foreground group-hover:text-primary">
                    {formatNumber(step.value, 0)}
                  </span>
                  <span
                    className={cn(
                      "flex items-center gap-1 text-[11.5px]",
                      step.status.ok ? "text-muted-foreground" : "text-amber-700 dark:text-amber-300",
                    )}
                  >
                    {step.status.ok ? (
                      <CircleCheck className="size-3 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                    ) : (
                      <TriangleAlert className="size-3 shrink-0" aria-hidden />
                    )}
                    {step.status.text}
                  </span>
                </Link>
                {index < steps.length - 1 ? (
                  <ChevronRight className="hidden size-4 shrink-0 text-muted-foreground/60 lg:block" aria-hidden />
                ) : null}
              </li>
            );
          })}
        </ol>
        <ContextMetrics slug={slug} overview={overview} />
      </CardContent>
    </Card>
  );
}

/** Compact technical indicators (detailed analysis lives in Observabilité). */
function ContextMetrics({ slug, overview }: { slug: string; overview: Overview }) {
  const { context, stats } = overview;
  const items: { label: string; value: string; title: string }[] = [];
  if (context.p95_latency_ms !== null) {
    items.push({
      label: "p95",
      value: context.p95_latency_ms >= 1000 ? `${formatNumber(context.p95_latency_ms / 1000, 2)} s` : `${formatNumber(context.p95_latency_ms, 0)} ms`,
      title: "Latence p95 de l'assemblage du contexte sur 7 jours (objectif < 1,5 s)",
    });
  }
  if (context.exclusion_rate !== null) {
    items.push({
      label: "exclusion",
      value: formatPercent(context.exclusion_rate),
      title: "Part des candidats écartés par la gouvernance ou le budget sur 7 jours",
    });
  }
  if (context.avg_tokens !== null) {
    items.push({ label: "tokens / contexte", value: formatNumber(context.avg_tokens, 0), title: "Taille moyenne des contextes servis" });
  }
  items.push({ label: "snapshots", value: formatNumber(stats.snapshots, 0), title: "Contextes partagés et versionnés" });
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-border px-3 pt-3 text-xs text-muted-foreground">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-baseline gap-1" title={item.title}>
          <span className="font-semibold tabular-nums text-foreground">{item.value}</span>
          {item.label}
        </span>
      ))}
      <Link
        href={projectHref(slug, "observability")}
        className="ml-auto inline-flex items-center gap-1 rounded font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        Analyse détaillée
        <ChevronRight className="size-3" aria-hidden />
      </Link>
    </div>
  );
}
