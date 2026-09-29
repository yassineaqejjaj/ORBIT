"use client";

import * as React from "react";
import { Brain, Combine, List, MousePointerClick, Network, Plus, SearchX, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Sheet, SheetBody, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useConsolidateMemory, useMe, useMembers } from "@/lib/api/hooks";
import type { MemoryItem } from "@/lib/api/types";
import { getMeta, JOB_STATUS_META, MEMORY_STATUS_META, MEMORY_STATUSES } from "@/lib/enums";
import { formatNumber, plural, shortId } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

import { MemoryCreateDialog } from "./memory-create-dialog";
import { MemoryDetail } from "./memory-detail";
import { MemoryFilters } from "./memory-filters";
import { MemoryGraphView } from "./memory-graph";
import { MemoryItemCard, MemoryItemCardSkeleton } from "./memory-item-card";
import type { MemoryPermissions } from "./memory-utils";
import {
  MEMORY_PAGE_SIZE,
  useGraphInsights,
  useMemoryResults,
  useMemoryStatusCounts,
  type MemoryFilters as MemoryFilterValues,
  type StatusCounts,
} from "./use-memory-data";
import { useMemoryUrlState, type MemoryUrlPatch, type MemoryView } from "./use-memory-url-state";

const GRAPH_LIMITS = [
  { value: "50", label: "50 nœuds" },
  { value: "150", label: "150 nœuds" },
  { value: "300", label: "300 nœuds" },
  { value: "600", label: "600 nœuds" },
] as const;

function useMounted(): boolean {
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  return mounted;
}

function SelectPrompt({ counts, onFilter }: { counts: StatusCounts; onFilter: (patch: MemoryUrlPatch) => void }) {
  return (
    <EmptyState
      variant="plain"
      size="lg"
      icon={<MousePointerClick />}
      title="Sélectionnez un élément"
      description="Son contenu, sa provenance jusqu'au paragraphe source, son historique complet, ses versions et ses relations s'afficheront ici."
    >
      <div className="mt-2 flex flex-wrap justify-center gap-1.5">
        {MEMORY_STATUSES.map((status) => {
          const meta = MEMORY_STATUS_META[status];
          const value = counts.byStatus[status];
          return (
            <button
              key={status}
              type="button"
              onClick={() => onFilter({ status })}
              className="inline-flex h-7 items-center gap-1.5 rounded-full border border-border bg-background px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className={cn("size-2 rounded-full", toneClasses(meta.tone).dot)} aria-hidden />
              {meta.label}
              <span className="font-semibold tabular-nums text-foreground">
                {typeof value === "number" ? formatNumber(value, 0) : "…"}
              </span>
            </button>
          );
        })}
      </div>
    </EmptyState>
  );
}

/** Mémoire: two-pane explorer (filters + list | detail), graph view, creation and consolidation. */
export function MemoryExplorer() {
  const { slug, canEdit, isOwner, project } = useCurrentProject();
  const { data: me } = useMe();
  const [state, update] = useMemoryUrlState();
  // Two queries (both false on the server) so a deep link never flashes the sheet open on desktop.
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const isMobile = useMediaQuery("(max-width: 1023.98px)");
  const mounted = useMounted();
  const members = useMembers(slug);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [graphLimit, setGraphLimit] = React.useState(150);
  const consolidate = useConsolidateMemory(slug);

  const filters = React.useMemo<MemoryFilterValues>(
    () => ({ scope: state.scope, status: state.status, kinds: state.kinds, q: state.q, history: state.history }),
    [state.scope, state.status, state.kinds, state.q, state.history],
  );
  const results = useMemoryResults(slug, filters, state.page);
  const counts = useMemoryStatusCounts(slug, {
    scope: state.scope,
    kinds: state.kinds,
    q: state.q,
    history: state.history,
  });
  const insights = useGraphInsights(slug);

  const permissions = React.useMemo<MemoryPermissions>(
    () => ({ canEdit, isOwner, meId: me?.id }),
    [canEdit, isOwner, me?.id],
  );

  const byId = React.useMemo(() => new Map(results.items.map((i) => [i.id, i])), [results.items]);
  const supersededTitle = React.useCallback(
    (item: MemoryItem) => {
      const id = item.superseded_by_id;
      if (!id) return null;
      return byId.get(id)?.title ?? insights.labels.get(id) ?? null;
    },
    [byId, insights.labels],
  );

  const select = React.useCallback((id: string) => update({ item: id }), [update]);
  const close = React.useCallback(() => update({ item: null }), [update]);

  // Bring the selected card into view (deep links, navigation from the graph or relations).
  React.useEffect(() => {
    if (!state.item || state.view !== "list") return;
    const el = document.querySelector<HTMLElement>(`[data-memory-id="${CSS.escape(state.item)}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [state.item, state.view, results.items]);

  const onConsolidate = () => {
    consolidate.mutate(undefined, {
      onSuccess: (job) => {
        toast.success("Consolidation lancée", {
          description: `Tâche ${shortId(job.id)} · ${getMeta(JOB_STATUS_META, job.status).label}. Les faits durables seront synthétisés en mémoire long terme.`,
        });
      },
    });
  };

  const hasFilters =
    state.scope !== "all" || state.status !== "all" || state.kinds.length > 0 || state.q.trim() !== "" || state.history;
  const detailInSheet = state.view === "graph" || isMobile;
  const sheetOpen = mounted && Boolean(state.item) && detailInSheet;

  const detail = state.item ? (
    <MemoryDetail
      key={state.item}
      slug={slug}
      itemId={state.item}
      permissions={permissions}
      members={members.data}
      labels={insights.labels}
      onOpenItem={select}
      onClose={detailInSheet ? undefined : close}
    />
  ) : null;

  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader
        icon={<Brain />}
        title="Mémoire"
        description={`Décisions, besoins, contraintes, risques, faits et préférences du projet ${project.name}, versionnés, gouvernés et traçables jusqu'à leur source.`}
        meta={
          typeof counts.total === "number" ? (
            <Badge tone="teal" size="md">
              {plural(counts.total, "élément")}
            </Badge>
          ) : null
        }
        actions={
          <>
            <SegmentedControl<MemoryView>
              value={state.view}
              onValueChange={(view) => update({ view })}
              aria-label="Mode d'affichage"
              options={[
                { value: "list", label: "Liste", icon: <List aria-hidden /> },
                { value: "graph", label: "Graphe", icon: <Network aria-hidden /> },
              ]}
            />
            <RequireRole min="editor">
              <Button
                variant="secondary"
                onClick={onConsolidate}
                loading={consolidate.isPending}
                leftIcon={<Combine aria-hidden />}
              >
                Consolider
              </Button>
              <Button onClick={() => setCreateOpen(true)} leftIcon={<Plus aria-hidden />}>
                Nouvelle mémoire
              </Button>
            </RequireRole>
          </>
        }
        className="pb-0"
      />

      {state.view === "graph" ? (
        <section className="grid gap-3" aria-label="Graphe des relations">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
              <Sparkles className="size-4 text-brand" aria-hidden />
              Survolez un nœud pour isoler ses relations ; cliquez sur une mémoire pour ouvrir son détail, sur un document
              pour ouvrir la source.
            </p>
            <SimpleSelect
              value={String(graphLimit)}
              onValueChange={(v) => setGraphLimit(Number(v))}
              options={GRAPH_LIMITS}
              size="sm"
              className="w-36"
              aria-label="Nombre maximal de nœuds"
            />
          </div>
          <MemoryGraphView slug={slug} limit={graphLimit} selectedId={state.item} onSelect={select} />
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-start">
          <section className="grid min-w-0 gap-3" aria-label="Éléments mémoire">
            <MemoryFilters state={state} onChange={update} counts={counts} />

            <div className="flex min-h-5 items-center justify-between gap-2 px-0.5 text-xs text-muted-foreground" aria-live="polite">
              <span>
                {results.isPending ? (
                  "Chargement…"
                ) : (
                  <>
                    <span className="font-semibold tabular-nums text-foreground">{formatNumber(results.total, 0)}</span>{" "}
                    {results.total > 1 ? "éléments" : "élément"}
                    {state.history ? " (versions antérieures incluses)" : ""}
                  </>
                )}
              </span>
              {results.isFetching && !results.isPending ? <Spinner className="size-3.5" label="Actualisation…" /> : null}
            </div>

            {results.error && results.items.length === 0 ? (
              <ErrorState error={results.error} onRetry={results.refetch} />
            ) : results.isPending ? (
              <div className="grid gap-2.5">
                {Array.from({ length: 6 }, (_, i) => (
                  <MemoryItemCardSkeleton key={i} />
                ))}
              </div>
            ) : results.items.length === 0 ? (
              hasFilters ? (
                <EmptyState
                  icon={<SearchX />}
                  title="Aucun élément ne correspond"
                  description="Élargissez la recherche ou retirez des filtres (portée, nature, statut)."
                  action={
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => update({ scope: "all", status: "all", kinds: [], q: "", history: false })}
                    >
                      Réinitialiser les filtres
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon={<Brain />}
                  title="La mémoire du projet est vide"
                  description="Les décisions, besoins, contraintes et risques sont extraits automatiquement à l'ingestion des sources. Vous pouvez aussi en ajouter manuellement."
                  action={
                    <RequireRole min="editor">
                      <Button size="sm" onClick={() => setCreateOpen(true)} leftIcon={<Plus aria-hidden />}>
                        Nouvelle mémoire
                      </Button>
                    </RequireRole>
                  }
                />
              )
            ) : (
              <>
                <ul className={cn("grid gap-2.5 transition-opacity", results.isPlaceholderData && "opacity-60")}>
                  {results.items.map((item) => (
                    <li key={item.id}>
                      <MemoryItemCard
                        item={item}
                        selected={state.item === item.id}
                        onSelect={select}
                        conflict={insights.conflictIds.has(item.id) || insights.conflictIds.has(item.lineage_id)}
                        supersededByTitle={supersededTitle(item)}
                      />
                    </li>
                  ))}
                </ul>
                {results.truncated ? (
                  <p className="px-0.5 text-xs text-muted-foreground">
                    Affichage limité aux 100 éléments les plus récents par nature : affinez la recherche pour voir les autres.
                  </p>
                ) : null}
                {results.paginated && results.total > MEMORY_PAGE_SIZE ? (
                  <Pagination
                    page={state.page}
                    pageSize={MEMORY_PAGE_SIZE}
                    total={results.total}
                    onPageChange={(page) => update({ page })}
                    disabled={results.isFetching}
                    compact
                  />
                ) : null}
              </>
            )}
          </section>

          <aside
            className="hidden min-w-0 rounded-xl border border-border bg-card shadow-xs lg:sticky lg:top-[4.5rem] lg:block lg:max-h-[calc(100dvh-5.5rem)] lg:overflow-y-auto"
            aria-label="Détail de l'élément mémoire"
          >
            {isDesktop ? (
              detail ? (
                <div className="p-5">{detail}</div>
              ) : (
                <SelectPrompt counts={counts} onFilter={update} />
              )
            ) : null}
          </aside>
        </div>
      )}

      <Sheet open={sheetOpen} onOpenChange={(open) => !open && close()}>
        <SheetContent side="right" size="lg" aria-describedby={undefined}>
          <SheetTitle className="sr-only">Détail de l&apos;élément mémoire</SheetTitle>
          <SheetBody className="pt-12">{sheetOpen ? detail : null}</SheetBody>
        </SheetContent>
      </Sheet>

      {canEdit ? (
        <MemoryCreateDialog
          slug={slug}
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={(item) => update({ item: item.id })}
          defaultScope={state.scope === "all" ? undefined : state.scope}
        />
      ) : null}
    </div>
  );
}
