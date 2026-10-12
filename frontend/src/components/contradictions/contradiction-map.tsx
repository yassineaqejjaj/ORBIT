"use client";

import * as React from "react";
import Link from "next/link";
import { CheckCircle2, GitCompareArrows } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { StatusBadge } from "@/components/domain/status-badge";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useContradictionMap } from "@/lib/api/hooks";
import type { ContradictionCluster, ContradictionSeverity } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const SEVERITY: Record<ContradictionSeverity, { label: string; hint: string; tone: "danger" | "warning" | "neutral"; stroke: string }> = {
  critical: {
    label: "Critique",
    hint: "Deux éléments validés se contredisent : la vérité de l’équipe est en désaccord avec elle-même.",
    tone: "danger",
    stroke: "#dc2626",
  },
  review: {
    label: "À arbitrer",
    hint: "Au moins un côté n’est encore qu’une proposition : un relecteur peut trancher.",
    tone: "warning",
    stroke: "#d97706",
  },
  minor: {
    label: "Mineure",
    hint: "Contradiction faible, sans paire validée.",
    tone: "neutral",
    stroke: "#6b7280",
  },
};

const W = 320;
const H = 230;

/** Items on an ellipse, one dashed line per contradiction (thicker when the detector is surer). */
function ClusterGraph({
  cluster,
  selected,
  onSelect,
}: {
  cluster: ContradictionCluster;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const n = cluster.items.length;
  const cx = W / 2;
  const cy = H / 2;
  const r = n === 2 ? 95 : Math.min(85, 40 + n * 12);
  const pos = new Map(
    cluster.items.map((item, i) => {
      const angle = (2 * Math.PI * i) / n - Math.PI / 2 + (n === 2 ? Math.PI / 2 : 0);
      return [item.id, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) * 0.62 }] as const;
    }),
  );
  const stroke = SEVERITY[cluster.severity].stroke;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${n} éléments en contradiction`} className="h-auto w-full">
      {cluster.edges.map((edge) => {
        const a = pos.get(edge.a);
        const b = pos.get(edge.b);
        if (!a || !b) return null;
        return (
          <g key={`${edge.a}-${edge.b}`}>
            <line
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={stroke}
              strokeWidth={1.5 + (edge.score ?? 0.5) * 2.5}
              strokeDasharray="6 4"
              strokeLinecap="round"
              opacity={0.85}
            />
            {edge.score !== null ? (
              <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 5} textAnchor="middle" className="fill-current text-[10px]" opacity={0.7}>
                {Math.round(edge.score * 100)} %
              </text>
            ) : null}
          </g>
        );
      })}
      {cluster.items.map((item) => {
        const p = pos.get(item.id);
        if (!p) return null;
        const keep = item.id === cluster.suggested_keep;
        return (
          <g
            key={item.id}
            onClick={() => onSelect(item.id)}
            className="cursor-pointer"
            role="button"
            tabIndex={0}
            aria-label={item.title}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(item.id)}
          >
            <circle
              cx={p.x}
              cy={p.y}
              r={item.id === selected ? 15 : 12}
              fill={item.status === "validated" ? "currentColor" : "transparent"}
              stroke="currentColor"
              strokeWidth={keep ? 3 : 1.5}
              className={keep ? "text-success" : "text-foreground"}
            />
            <text x={p.x} y={p.y + 28} textAnchor="middle" className="fill-current text-[10.5px]">
              {item.title.length > 24 ? `${item.title.slice(0, 23)}…` : item.title}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function ClusterCard({ cluster, slug }: { cluster: ContradictionCluster; slug: string }) {
  const meta = SEVERITY[cluster.severity];
  const [selected, setSelected] = React.useState<string | null>(cluster.suggested_keep);
  return (
    <section className="rounded-xl border border-border bg-surface p-4 shadow-panel" aria-label={`Contradiction ${meta.label}`}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone={meta.tone}>{meta.label}</Badge>
        <span className="text-sm text-muted-foreground">{meta.hint}</span>
        {cluster.max_classification >= 2 ? <ClassificationBadge level={cluster.max_classification} /> : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <ClusterGraph cluster={cluster} selected={selected} onSelect={setSelected} />
        <div className="grid content-start gap-2.5">
          {cluster.items.map((item) => (
            <article key={item.id} className={cn("rounded-lg border p-3 text-sm", item.id === selected ? "border-brand" : "border-border")}>
              <div className="flex flex-wrap items-center gap-1.5">
                <button type="button" className="text-left font-medium hover:underline" onClick={() => setSelected(item.id)}>
                  {item.title}
                </button>
                <MemoryKindBadge kind={item.kind as never} size="sm" />
                <StatusBadge kind="memory" status={item.status} size="sm" />
                {item.classification >= 2 ? <ClassificationBadge level={item.classification} showLabel={false} /> : null}
                {item.id === cluster.suggested_keep ? (
                  <Badge tone="success" icon={<CheckCircle2 />}>
                    À conserver (le plus fiable)
                  </Badge>
                ) : null}
              </div>
              <p className="mt-1.5 text-muted-foreground">{item.excerpt}</p>
              <Link className="mt-1.5 inline-block text-xs text-brand hover:underline" href={`${projectHref(slug, "memory")}?item=${item.id}`}>
                Ouvrir dans la mémoire
              </Link>
            </article>
          ))}
          {cluster.edges.some((e) => e.explanation) ? (
            <ul className="grid gap-1 text-xs text-muted-foreground">
              {cluster.edges
                .filter((e) => e.explanation)
                .map((e) => (
                  <li key={`${e.a}-${e.b}`}>— {e.explanation}</li>
                ))}
            </ul>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export function ContradictionMapView() {
  const { slug } = useCurrentProject();
  const map = useContradictionMap(slug);
  const [filter, setFilter] = React.useState<ContradictionSeverity | "all">("all");
  const clusters = (map.data?.clusters ?? []).filter((c) => filter === "all" || c.severity === filter);
  const top = Math.max(0, ...(map.data?.clusters ?? []).map((c) => c.max_classification));
  return (
    <div className="grid gap-5">
      <PageHeader
        icon={<GitCompareArrows />}
        title="Contradictions"
        description="Ce que la mémoire du projet affirme sans pouvoir tout garder vrai, regroupé et classé. Seuls les éléments auxquels vous avez accès apparaissent."
      >
        {map.data ? (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrer par gravité">
            {(["all", "critical", "review", "minor"] as const).map((key) => {
              const count = key === "all" ? map.data.clusters.length : map.data.counts[key];
              return (
                <button
                  key={key}
                  type="button"
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-sm",
                    filter === key ? "border-brand bg-brand/10" : "border-border hover:border-border-strong",
                  )}
                >
                  {key === "all" ? "Toutes" : SEVERITY[key].label} · {count}
                </button>
              );
            })}
          </div>
        ) : null}
      </PageHeader>
      {top >= 2 ? <ClassificationBanner level={top} context="display" /> : null}
      {map.isLoading ? <Skeleton className="h-72 rounded-xl" /> : null}
      {map.isError ? <ErrorState error={map.error} onRetry={() => map.refetch()} /> : null}
      {map.data && clusters.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 />}
          title="Aucune contradiction"
          description="Rien dans la mémoire que vous pouvez consulter ne se contredit."
        />
      ) : null}
      {clusters.map((cluster) => (
        <ClusterCard key={cluster.items.map((i) => i.id).join("-")} cluster={cluster} slug={slug} />
      ))}
    </div>
  );
}
