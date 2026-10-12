"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Hourglass, MinusCircle, PencilLine, PlusCircle } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { MemoryKindBadge } from "@/components/domain/memory-kind-badge";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useAsOfDiff } from "@/lib/api/hooks";
import type { AsOfDiff, KnownItem } from "@/lib/api/types";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

const PRESETS = [
  { label: "7 jours", days: 7 },
  { label: "30 jours", days: 30 },
  { label: "90 jours", days: 90 },
  { label: "1 an", days: 365 },
] as const;

const WHY: Record<AsOfDiff["removed"][number]["why"], string> = {
  replaced: "Remplacé",
  obsolete: "Devenu obsolète",
  expired: "Arrivé à échéance",
  forgotten: "Oublié",
  unknown: "Retiré",
};

const dayInput = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000);

function Item({ item, slug }: { item: KnownItem; slug: string }) {
  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <Link className="font-medium hover:underline" href={`${projectHref(slug, "memory")}?item=${item.id}`}>
          {item.title}
        </Link>
        <MemoryKindBadge kind={item.kind as never} size="sm" />
        {item.classification >= 2 ? <ClassificationBadge level={item.classification} showLabel={false} /> : null}
      </div>
      <p className="text-[13px] text-muted-foreground">{item.excerpt}</p>
    </div>
  );
}

function Column({ icon, title, count, tone, children }: { icon: React.ReactNode; title: string; count: number; tone: string; children: React.ReactNode }) {
  return (
    <section className="grid content-start gap-3 rounded-xl border border-border bg-surface p-4 shadow-panel" aria-label={title}>
      <h2 className={cn("flex items-center gap-2 text-sm font-semibold", tone)}>
        {icon} {title} <span className="font-normal text-muted-foreground">· {count}</span>
      </h2>
      {count === 0 ? <p className="text-sm text-muted-foreground">Rien sur cette période.</p> : children}
    </section>
  );
}

export function EvolutionView() {
  const { slug } = useCurrentProject();
  const [from, setFrom] = React.useState(() => dayInput(daysAgo(30)));
  const [to, setTo] = React.useState(() => dayInput(new Date()));
  const valid = from < to;
  const diff = useAsOfDiff(slug, valid ? `${from}T00:00:00Z` : "", valid ? `${to}T23:59:59Z` : "");
  const data = diff.data;
  return (
    <div className="grid gap-5">
      <PageHeader
        icon={<Hourglass />}
        title="Évolution"
        description="Ce que le projet savait à une date, comparé à une autre : ce qui est apparu, ce qui a disparu (et pourquoi) et ce qui a été réécrit. Seuls les éléments auxquels vous avez accès comptent."
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Période">
            {PRESETS.map((p) => (
              <button
                key={p.days}
                type="button"
                onClick={() => {
                  setFrom(dayInput(daysAgo(p.days)));
                  setTo(dayInput(new Date()));
                }}
                className="rounded-full border border-border px-3 py-1 text-sm hover:border-border-strong"
              >
                {p.label}
              </button>
            ))}
          </div>
          <label className="grid gap-0.5 text-xs text-muted-foreground">
            Du
            <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} className="h-9 rounded-md border border-border bg-surface px-2 text-sm text-foreground" />
          </label>
          <label className="grid gap-0.5 text-xs text-muted-foreground">
            Au
            <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} className="h-9 rounded-md border border-border bg-surface px-2 text-sm text-foreground" />
          </label>
        </div>
      </PageHeader>
      {!valid ? <p className="text-sm text-muted-foreground">La date de départ doit précéder celle d’arrivée.</p> : null}
      {data && data.max_classification >= 2 ? <ClassificationBanner level={data.max_classification} context="display" /> : null}
      {diff.isLoading && valid ? <Skeleton className="h-64 rounded-xl" /> : null}
      {diff.isError ? <ErrorState error={diff.error} onRetry={() => diff.refetch()} /> : null}
      {data && data.counts.added + data.counts.removed + data.counts.changed === 0 ? (
        <EmptyState icon={<Hourglass />} title="Aucun changement" description="La mémoire que vous pouvez consulter est la même aux deux dates." />
      ) : null}
      {data && data.counts.added + data.counts.removed + data.counts.changed > 0 ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Column icon={<PlusCircle className="size-4" />} title="Apparu" count={data.counts.added} tone="text-success">
            {data.added.map((item) => (
              <Item key={item.id} item={item} slug={slug} />
            ))}
          </Column>
          <Column icon={<MinusCircle className="size-4" />} title="Disparu" count={data.counts.removed} tone="text-danger">
            {data.removed.map((r) => (
              <div key={r.item.id} className="grid gap-1.5">
                <Item item={r.item} slug={slug} />
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <Badge tone="neutral">{WHY[r.why]}</Badge>
                  {r.replaced_by ? (
                    <>
                      <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
                      <Link className="hover:underline" href={`${projectHref(slug, "memory")}?item=${r.replaced_by.id}`}>
                        {r.replaced_by.title}
                      </Link>
                    </>
                  ) : null}
                </div>
              </div>
            ))}
          </Column>
          <Column icon={<PencilLine className="size-4" />} title="Réécrit" count={data.counts.changed} tone="text-warning">
            {data.changed.map((c) => (
              <div key={c.after.id} className="grid gap-1.5">
                <Item item={c.after} slug={slug} />
                <p className="rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
                  <span className="font-medium">Avant ({plural(c.before.version, "version", "versions")}) :</span> {c.before.excerpt}
                </p>
              </div>
            ))}
          </Column>
        </div>
      ) : null}
    </div>
  );
}
