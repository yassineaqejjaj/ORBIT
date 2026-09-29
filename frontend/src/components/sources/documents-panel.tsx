"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FileSearch, FilterX, Inbox, RefreshCw, Search, ShieldAlert } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { RelativeTime } from "@/components/domain/relative-time";
import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useDocuments } from "@/lib/api/hooks";
import type { DocumentListParams, Source } from "@/lib/api/types";
import {
  CLASSIFICATION_META,
  CLASSIFICATIONS,
  DOCUMENT_STATUS_META,
  DOCUMENT_STATUSES,
  getMeta,
  isEnumValue,
  SOURCE_KIND_META,
  SOURCE_KINDS,
  toClassification,
  type Classification,
} from "@/lib/enums";
import { formatDate, formatDateTime, formatNumber, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AddContentMenu } from "./add-content-menu";
import { DocumentStatusBadge, isDocumentActive } from "./document-status";
import { parsePositiveInt, useUrlParams } from "./use-url-params";

const PAGE_SIZE = 25;
const POLL_MS = 3_000;
const ALL = "__all__";
const COLUMNS = 8;

function documentHref(slug: string, id: string): string {
  return `${projectHref(slug, "sources")}/${encodeURIComponent(id)}`;
}

function RowsSkeleton() {
  return (
    <>
      {Array.from({ length: 8 }, (_, i) => (
        <TableRow key={i}>
          <TableCell>
            <div className="flex items-center gap-2.5">
              <Skeleton className="size-6 rounded-md" />
              <div className="grid flex-1 gap-1.5">
                <Skeleton className="h-3.5 w-56 max-w-full" />
                <Skeleton className="h-3 w-24" />
              </div>
            </div>
          </TableCell>
          {Array.from({ length: COLUMNS - 1 }, (__, j) => (
            <TableCell key={j}>
              <Skeleton className="h-3.5 w-16" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

export interface DocumentsPanelProps {
  slug: string;
  sources: readonly Source[] | undefined;
  sourcesLoading: boolean;
}

/** Documents tab: debounced search, filters (source, kind, status, classification), pagination, live refresh. */
export function DocumentsPanel({ slug, sources, sourcesLoading }: DocumentsPanelProps) {
  const router = useRouter();
  const { get, set } = useUrlParams();

  const urlQ = get("q") ?? "";
  const sourceId = get("source") ?? "";
  const kindParam = get("kind");
  const statusParam = get("status");
  const classificationParam = get("classification");
  const page = parsePositiveInt(get("page"));

  const kind = isEnumValue(SOURCE_KINDS, kindParam) ? kindParam : undefined;
  const status = isEnumValue(DOCUMENT_STATUSES, statusParam) ? statusParam : undefined;
  const classification: Classification | undefined =
    classificationParam !== null && /^[0-3]$/.test(classificationParam) ? toClassification(Number(classificationParam)) : undefined;

  // Debounced search box synced with ?q=
  const [qInput, setQInput] = React.useState(urlQ);
  const debouncedQ = useDebouncedValue(qInput.trim(), 300);
  React.useEffect(() => {
    setQInput((current) => (current.trim() === urlQ ? current : urlQ));
  }, [urlQ]);
  React.useEffect(() => {
    // Only push once the debounce has settled on the current input (avoids re-applying a stale value).
    if (debouncedQ === qInput.trim() && debouncedQ !== urlQ) set({ q: debouncedQ, page: null });
  }, [debouncedQ, qInput, urlQ, set]);

  const params: DocumentListParams = {
    q: urlQ || undefined,
    source_id: sourceId || undefined,
    source_kind: kind,
    status,
    classification,
    page,
    page_size: PAGE_SIZE,
  };

  const documents = useDocuments(slug, params, {
    refetchInterval: (query) => (query.state.data?.items.some((d) => isDocumentActive(d.status)) ? POLL_MS : false),
  });

  const filtersActive = Boolean(urlQ || sourceId || kind || status || classification !== undefined);
  const activeCount = documents.data?.items.filter((d) => isDocumentActive(d.status)).length ?? 0;

  const sourceOptions = React.useMemo<SimpleSelectOption<string>[]>(
    () => [
      { value: ALL, label: "Toutes les sources" },
      ...(sources ?? []).map((s) => ({
        value: s.id,
        label: s.name,
        icon: <SourceKindIcon kind={s.kind} size="sm" />,
      })),
    ],
    [sources],
  );
  const kindOptions = React.useMemo<SimpleSelectOption<string>[]>(
    () => [
      { value: ALL, label: "Tous les types" },
      ...SOURCE_KINDS.map((k) => ({ value: k, label: SOURCE_KIND_META[k].label, icon: <SourceKindIcon kind={k} size="sm" /> })),
    ],
    [],
  );
  const statusOptions = React.useMemo<SimpleSelectOption<string>[]>(
    () => [
      { value: ALL, label: "Tous les statuts" },
      ...DOCUMENT_STATUSES.map((s) => ({ value: s, label: DOCUMENT_STATUS_META[s].label })),
    ],
    [],
  );
  const classificationOptions = React.useMemo<SimpleSelectOption<string>[]>(
    () => [
      { value: ALL, label: "Toutes classifications" },
      ...CLASSIFICATIONS.map((c) => ({ value: String(c), label: `${CLASSIFICATION_META[c].code} · ${CLASSIFICATION_META[c].label}` })),
    ],
    [],
  );

  const resetFilters = () => {
    setQInput("");
    set({ q: null, source: null, kind: null, status: null, classification: null, page: null });
  };

  const data = documents.data;
  const hasSensitive = data?.items.some((d) => d.classification >= 2) ?? false;

  return (
    <div className="grid gap-4">
      <div className="grid gap-2 lg:grid-cols-[minmax(16rem,1fr)_repeat(4,minmax(0,11rem))] lg:items-center">
        <Input
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder="Rechercher un titre, un auteur, un identifiant…"
          leftIcon={<Search aria-hidden />}
          aria-label="Rechercher des documents"
          size="sm"
          rightSlot={
            qInput ? (
              <Button variant="ghost" size="icon-xs" onClick={() => setQInput("")} aria-label="Effacer la recherche">
                <FilterX aria-hidden />
              </Button>
            ) : undefined
          }
        />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:contents">
          <SimpleSelect<string>
            size="sm"
            value={sourceId || ALL}
            onValueChange={(v) => set({ source: v === ALL ? null : v, page: null })}
            options={sourceOptions}
            disabled={sourcesLoading}
            aria-label="Filtrer par source"
          />
          <SimpleSelect<string>
            size="sm"
            value={kind ?? ALL}
            onValueChange={(v) => set({ kind: v === ALL ? null : v, page: null })}
            options={kindOptions}
            aria-label="Filtrer par type de source"
          />
          <SimpleSelect<string>
            size="sm"
            value={status ?? ALL}
            onValueChange={(v) => set({ status: v === ALL ? null : v, page: null })}
            options={statusOptions}
            aria-label="Filtrer par statut"
          />
          <SimpleSelect<string>
            size="sm"
            value={classification !== undefined ? String(classification) : ALL}
            onValueChange={(v) => set({ classification: v === ALL ? null : v, page: null })}
            options={classificationOptions}
            aria-label="Filtrer par classification"
          />
        </div>
      </div>

      <div className="flex min-h-6 flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {data ? (
          <span className="tabular-nums">
            {plural(data.total, "document")}
            {filtersActive ? " correspondant aux filtres" : ""}
          </span>
        ) : null}
        {activeCount > 0 ? (
          <Badge tone="blue" pulse>
            {plural(activeCount, "document")} en traitement · actualisation automatique
          </Badge>
        ) : null}
        {documents.isFetching && !documents.isPending ? <RefreshCw className="size-3 animate-spin" aria-label="Actualisation" /> : null}
        {filtersActive ? (
          <Button variant="link" size="xs" className="ml-auto text-xs" onClick={resetFilters} leftIcon={<FilterX aria-hidden />}>
            Réinitialiser les filtres
          </Button>
        ) : null}
      </div>

      {hasSensitive ? (
        <p className="flex items-center gap-2 text-xs text-amber-800 dark:text-amber-200">
          <ShieldAlert className="size-3.5 shrink-0" aria-hidden />
          Cette liste contient des documents classifiés C2/C3 : leur contenu n&apos;est servi qu&apos;aux personnes et agents
          habilités.
        </p>
      ) : null}

      {documents.isError ? (
        <ErrorState error={documents.error} onRetry={() => void documents.refetch()} />
      ) : !documents.isPending && data && data.items.length === 0 ? (
        filtersActive ? (
          <EmptyState
            icon={<FileSearch />}
            title="Aucun document ne correspond"
            description="Modifiez la recherche ou retirez des filtres pour élargir les résultats."
            action={
              <Button variant="secondary" size="sm" onClick={resetFilters} leftIcon={<FilterX aria-hidden />}>
                Réinitialiser les filtres
              </Button>
            }
          />
        ) : (
          <EmptyState
            size="lg"
            icon={<Inbox />}
            title="Aucun document pour l'instant"
            description="Téléversez des fichiers, rédigez une note ou importez un lot de tickets, fiches CRM ou retours utilisateurs : chaque contenu passe par le pipeline d'ingestion (extraction, données personnelles, classification, indexation)."
            action={
              <RequireRole min="editor" fallback={<p className="text-xs text-muted-foreground">Un éditeur du projet peut ajouter des contenus.</p>}>
                <AddContentMenu slug={slug} label="Ajouter du contenu" align="start" />
              </RequireRole>
            }
          />
        )
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-72">Document</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Classification</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead className="text-right">Données perso.</TableHead>
                <TableHead className="text-right">Version</TableHead>
                <TableHead className="text-right">Extraits</TableHead>
                <TableHead>Date métier</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.isPending ? (
                <RowsSkeleton />
              ) : (
                data?.items.map((doc) => {
                  const href = documentHref(slug, doc.id);
                  const forgotten = doc.status === "forgotten";
                  return (
                    <TableRow
                      key={doc.id}
                      interactive
                      onClick={(e) => {
                        if ((e.target as HTMLElement).closest("a,button,[role=button]")) return;
                        router.push(href);
                      }}
                      className={cn(forgotten && "opacity-70")}
                    >
                      <TableCell>
                        <div className="flex min-w-0 items-center gap-2.5">
                          <SourceKindIcon kind={doc.source_kind} chip size="sm" />
                          <div className="grid min-w-0 gap-0.5">
                            <Link
                              href={href}
                              className={cn(
                                "truncate rounded font-medium text-foreground hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                forgotten && "line-through decoration-muted-foreground/60",
                              )}
                            >
                              {doc.title}
                            </Link>
                            <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                              <span className="truncate">{getMeta(SOURCE_KIND_META, doc.source_kind).label}</span>
                              {doc.external_id ? <span className="truncate font-mono text-[11px]">· {doc.external_id}</span> : null}
                              {doc.author ? <span className="truncate">· {doc.author}</span> : null}
                            </span>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-44">
                        <button
                          type="button"
                          onClick={() => set({ source: doc.source_id, page: null })}
                          className="block max-w-full truncate rounded text-left text-muted-foreground hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          title={`Filtrer sur la source « ${doc.source_name} »`}
                        >
                          {doc.source_name || "—"}
                        </button>
                      </TableCell>
                      <TableCell>
                        <ClassificationBadge level={doc.classification} />
                      </TableCell>
                      <TableCell>
                        <DocumentStatusBadge status={doc.status} reason={doc.status_reason} />
                      </TableCell>
                      <TableCell className="text-right">
                        {doc.pii_count > 0 ? (
                          <Badge tone="pink" title="Données personnelles détectées et caviardées pour les agents">
                            {formatNumber(doc.pii_count, 0)}
                          </Badge>
                        ) : (
                          <span className="text-subtle-foreground">0</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {doc.current_version > 1 ? (
                          <Badge tone="violet" variant="outline" title="Plusieurs versions ingérées">
                            v{doc.current_version}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">v{doc.current_version}</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {formatNumber(doc.chunk_count, 0)}
                      </TableCell>
                      <TableCell>
                        <div className="grid gap-0.5 whitespace-nowrap">
                          <SimpleTooltip content={`Date métier : ${formatDateTime(doc.source_updated_at ?? doc.created_at)}`}>
                            <span className="text-[13px] text-foreground">{formatDate(doc.source_updated_at ?? doc.created_at)}</span>
                          </SimpleTooltip>
                          <span className="text-xs text-muted-foreground">
                            maj <RelativeTime date={doc.updated_at} />
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
          {data && data.total > 0 ? (
            <div className="border-t border-border px-4 py-3">
              <Pagination
                page={data.page}
                pageSize={data.page_size || PAGE_SIZE}
                total={data.total}
                onPageChange={(p) => set({ page: p > 1 ? p : null })}
                disabled={documents.isFetching}
              />
            </div>
          ) : null}
        </Card>
      )}
    </div>
  );
}
