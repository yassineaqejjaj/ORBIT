"use client";

import * as React from "react";
import Link from "next/link";
import { BellRing, History, Webhook } from "lucide-react";

import { projectHref } from "@/components/layout/nav";
import { useUrlParams } from "@/components/sources/use-url-params";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useChanges, useSubscription } from "@/lib/api/features-feed";
import { cn } from "@/lib/utils";
import { CHANGE_FAMILIES } from "./change-meta";
import { ChangesTimeline } from "./changes-timeline";
import { DigestCard, SinceSnapshotCard, SubscriptionDialog } from "./changes-side";

const PAGE_SIZE = 50;
const DIGEST_LABELS = { off: null, daily: "Résumé quotidien", weekly: "Résumé hebdomadaire" } as const;

/** « Fil des changements » (docs/FEATURES.md F2): day-grouped timeline filtered by rights. */
export function ChangesView() {
  const { slug, project, isOwner } = useCurrentProject();
  const { get, set } = useUrlParams();
  const families = (get("types") ?? "").split(",").filter(Boolean);
  const page = Math.max(1, Number(get("page") ?? 1) || 1);
  const types = CHANGE_FAMILIES.filter((f) => families.includes(f.value)).flatMap((f) => f.types);
  const changes = useChanges(slug, { types, page, page_size: PAGE_SIZE });
  const subscription = useSubscription(slug);
  const [subscriptionOpen, setSubscriptionOpen] = React.useState(false);
  const digestLabel = subscription.data ? DIGEST_LABELS[subscription.data.digest] : null;

  const toggleFamily = (value: string) => {
    const next = families.includes(value) ? families.filter((f) => f !== value) : [...families, value];
    set({ types: next.length ? next.join(",") : null, page: null });
  };

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        icon={<History />}
        eyebrow={project.name}
        title="Fil des changements"
        description="Décisions validées ou remplacées, contradictions, nouvelles sources et snapshots — uniquement ce que vos droits vous permettent de voir."
        meta={
          digestLabel ? (
            <Badge tone="blue" size="sm" icon={<BellRing />}>
              {digestLabel}
            </Badge>
          ) : null
        }
        actions={
          <>
            {isOwner ? (
              <Button variant="secondary" size="sm" asChild>
                <Link href={`${projectHref(slug, "settings")}?tab=webhooks`}>
                  <Webhook aria-hidden />
                  Webhooks
                </Link>
              </Button>
            ) : null}
            <Button size="sm" onClick={() => setSubscriptionOpen(true)}>
              <BellRing aria-hidden />
              M&apos;abonner
            </Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
        <div className="grid min-w-0 content-start gap-4">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrer par type de changement">
            <FilterChip active={families.length === 0} onClick={() => set({ types: null, page: null })}>
              Tout
            </FilterChip>
            {CHANGE_FAMILIES.map((family) => (
              <FilterChip
                key={family.value}
                active={families.includes(family.value)}
                onClick={() => toggleFamily(family.value)}
              >
                {family.label}
              </FilterChip>
            ))}
          </div>

          {changes.isPending ? (
            <div className="grid gap-3" aria-busy="true" aria-label="Chargement du fil">
              {Array.from({ length: 6 }, (_, i) => (
                <div key={i} className="flex gap-3">
                  <Skeleton className="size-7 rounded-full" />
                  <div className="grid flex-1 gap-1.5">
                    <Skeleton className="h-3 w-32" />
                    <Skeleton className="h-4 w-full max-w-md" />
                  </div>
                </div>
              ))}
            </div>
          ) : changes.isError ? (
            <ErrorState error={changes.error} onRetry={() => void changes.refetch()} />
          ) : changes.data.items.length === 0 ? (
            <EmptyState
              icon={<History />}
              title="Aucun changement"
              description={
                families.length
                  ? "Aucun changement de ce type pour l'instant."
                  : "Les validations, remplacements, nouvelles sources et snapshots apparaîtront ici au fil de l'eau."
              }
            />
          ) : (
            <>
              <ChangesTimeline slug={slug} events={changes.data.items} />
              <Pagination
                page={page}
                pageSize={PAGE_SIZE}
                total={changes.data.total}
                onPageChange={(next) => set({ page: next === 1 ? null : String(next) })}
                disabled={changes.isFetching}
              />
            </>
          )}
        </div>
        <aside className="grid content-start gap-4" aria-label="Snapshots et résumé">
          <SinceSnapshotCard slug={slug} />
          <DigestCard slug={slug} />
        </aside>
      </div>
      <SubscriptionDialog slug={slug} open={subscriptionOpen} onOpenChange={setSubscriptionOpen} />
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "h-7 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-brand bg-brand-soft text-brand"
          : "border-border bg-card text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      {children}
    </button>
  );
}
