"use client";

import * as React from "react";
import { Database, FileCheck2, Filter, Gauge, Gavel, Telescope } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { Progress } from "@/components/ui/progress";
import { StatCard } from "@/components/ui/stat-card";
import type { Overview } from "@/lib/api/types";
import type { Tone } from "@/lib/enums";
import { formatMs, formatNumber, formatPercent, formatTokens, plural } from "@/lib/format";

/** p95 target from ARCHITECTURE §9 (CPU demo data set). */
export const P95_TARGET_MS = 1500;

function latencyTone(p95: number | null): Tone {
  if (p95 === null) return "neutral";
  if (p95 <= P95_TARGET_MS) return "green";
  if (p95 <= P95_TARGET_MS * 2) return "amber";
  return "red";
}

export function OverviewKpis({ slug, overview }: { slug: string; overview: Overview }) {
  const { stats, context } = overview;
  const indexedRatio = stats.documents > 0 ? stats.documents_indexed / stats.documents : null;
  const p95 = context.p95_latency_ms;

  return (
    <section aria-label="Indicateurs clés" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatCard
        label="Sources"
        value={formatNumber(stats.sources, 0)}
        icon={<Database />}
        tone="blue"
        hint={plural(stats.documents, "document")}
        href={`${projectHref(slug, "sources")}?tab=sources`}
      />
      <StatCard
        label="Documents indexés"
        value={formatNumber(stats.documents_indexed, 0)}
        icon={<FileCheck2 />}
        tone="teal"
        hint={
          indexedRatio === null
            ? "Aucun document"
            : `${formatPercent(indexedRatio)} des ${formatNumber(stats.documents, 0)} documents`
        }
        href={`${projectHref(slug, "sources")}?status=indexed`}
      >
        {indexedRatio !== null ? (
          <Progress value={indexedRatio * 100} tone="teal" size="xs" aria-label="Part des documents indexés" />
        ) : null}
      </StatCard>
      <StatCard
        label="Décisions validées"
        value={formatNumber(stats.validated_decisions, 0)}
        icon={<Gavel />}
        tone="green"
        hint={`${formatNumber(stats.memory_items, 0)} éléments de mémoire`}
        href={`${projectHref(slug, "memory")}?kind=decision&status=validated`}
      />
      <StatCard
        label="Contextes servis (7 j)"
        value={formatNumber(context.requests_7d, 0)}
        icon={<Telescope />}
        tone="orange"
        hint={context.avg_tokens !== null ? `${formatTokens(context.avg_tokens)} en moyenne` : "Aucun contexte servi"}
        href={projectHref(slug, "observability")}
      />
      <StatCard
        label="Latence p95"
        value={p95 !== null ? formatMs(p95) : "—"}
        icon={<Gauge />}
        tone={latencyTone(p95)}
        hint={
          p95 === null
            ? "Pas encore de mesure"
            : p95 <= P95_TARGET_MS
              ? `Objectif < ${formatMs(P95_TARGET_MS)} tenu`
              : `Au-dessus de l'objectif (${formatMs(P95_TARGET_MS)})`
        }
        href={projectHref(slug, "observability")}
      />
      <StatCard
        label="Taux d'exclusion"
        value={context.exclusion_rate !== null ? formatPercent(context.exclusion_rate) : "—"}
        icon={<Filter />}
        tone="violet"
        hint={
          context.avg_included !== null
            ? `${formatNumber(context.avg_included, 1)} éléments retenus par contexte`
            : "Candidats écartés par la gouvernance"
        }
        href={projectHref(slug, "explorer")}
      />
    </section>
  );
}

export function OverviewKpisSkeleton() {
  return (
    <section aria-hidden className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {["Sources", "Documents indexés", "Décisions validées", "Contextes servis (7 j)", "Latence p95", "Taux d'exclusion"].map(
        (label) => (
          <StatCard key={label} label={label} value="—" loading hint="…" />
        ),
      )}
    </section>
  );
}
