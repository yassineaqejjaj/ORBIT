"use client";

import * as React from "react";
import { DatabaseZap, FileStack, MoreHorizontal, PencilLine, Plus, UploadCloud } from "lucide-react";

import { RequireRole, useHasRole } from "@/components/auth/require-role";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { SourceKindIcon } from "@/components/domain/source-kind-icon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useMembers } from "@/lib/api/hooks";
import type { ApiError } from "@/lib/api/client";
import type { Source } from "@/lib/api/types";
import { getMeta, SOURCE_KIND_META, SOURCE_TRUST_META } from "@/lib/enums";
import { formatNumber, formatPercent, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AclChips } from "./acl-chips";
import { SourceDialog } from "./source-dialog";
import { UploadDialog } from "./upload-dialog";

function SourceCardSkeleton() {
  return (
    <Card className="grid gap-4 p-4">
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid flex-1 gap-1.5">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
      <Skeleton className="h-3 w-full" />
      <div className="grid grid-cols-4 gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    </Card>
  );
}

function Count({ label, value, className }: { label: string; value: number; className?: string }) {
  return (
    <div className="grid gap-0.5 rounded-md bg-muted/50 px-2.5 py-1.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className={cn("text-sm font-semibold tabular-nums text-foreground", className)}>{formatNumber(value, 0)}</span>
    </div>
  );
}

export interface SourcesPanelProps {
  slug: string;
  sources: readonly Source[] | undefined;
  isPending: boolean;
  error: ApiError | null;
  onRetry: () => void;
  /** Show the documents of a source (switches to the Documents tab with the filter). */
  onShowDocuments: (sourceId: string) => void;
}

/** Sources tab: one card per business source with its counters, defaults and quick actions. */
export function SourcesPanel({ slug, sources, isPending, error, onRetry, onShowDocuments }: SourcesPanelProps) {
  const canEdit = useHasRole("editor");
  const members = useMembers(slug);
  const [dialogSource, setDialogSource] = React.useState<Source | null>(null);
  const [sourceDialogOpen, setSourceDialogOpen] = React.useState(false);
  const [uploadSourceId, setUploadSourceId] = React.useState<string | null>(null);

  const openCreate = () => {
    setDialogSource(null);
    setSourceDialogOpen(true);
  };
  const openEdit = (source: Source) => {
    setDialogSource(source);
    setSourceDialogOpen(true);
  };

  const sorted = React.useMemo(
    () => [...(sources ?? [])].sort((a, b) => b.counts.documents - a.counts.documents || a.name.localeCompare(b.name, "fr")),
    [sources],
  );

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {sources ? plural(sources.length, "source connectée", "sources connectées") : "Chargement des sources…"}
        </p>
        <RequireRole min="editor">
          <Button variant="secondary" size="sm" leftIcon={<Plus aria-hidden />} onClick={openCreate}>
            Nouvelle source
          </Button>
        </RequireRole>
      </div>

      {error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : isPending ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <SourceCardSkeleton key={i} />
          ))}
        </div>
      ) : sorted.length === 0 ? (
        <EmptyState
          size="lg"
          icon={<DatabaseZap />}
          title="Aucune source"
          description="Les sources sont créées automatiquement à la première ingestion, ou manuellement pour fixer une classification et des droits par défaut."
          action={
            canEdit ? (
              <Button leftIcon={<Plus aria-hidden />} onClick={openCreate}>
                Créer une source
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {sorted.map((source) => {
            const { counts } = source;
            const indexedRatio = counts.documents > 0 ? counts.indexed / counts.documents : 0;
            return (
              <Card key={source.id} className="flex flex-col">
                <div className="flex items-start gap-3 p-4 pb-3">
                  <SourceKindIcon kind={source.kind} chip className="[&>span]:size-9 [&_svg]:size-[18px]" />
                  <div className="grid min-w-0 flex-1 gap-0.5">
                    <h3 className="truncate text-sm font-semibold text-foreground" title={source.name}>
                      {source.name}
                    </h3>
                    <p className="truncate text-xs text-muted-foreground">
                      {getMeta(SOURCE_KIND_META, source.kind).label}
                      {source.effective_trust ? ` · ${SOURCE_TRUST_META[source.effective_trust].label.toLowerCase()}` : ""}
                      {source.last_ingested_at ? (
                        <>
                          {" · dernière ingestion "}
                          <RelativeTime date={source.last_ingested_at} />
                        </>
                      ) : (
                        " · jamais ingérée"
                      )}
                    </p>
                  </div>
                  <RequireRole min="editor">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`Actions pour ${source.name}`}>
                          <MoreHorizontal aria-hidden />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => setUploadSourceId(source.id)}>
                          <UploadCloud aria-hidden />
                          Téléverser dans cette source
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => openEdit(source)}>
                          <PencilLine aria-hidden />
                          Modifier la source
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </RequireRole>
                </div>

                <div className="grid flex-1 content-start gap-3 px-4 pb-4">
                  {source.description ? (
                    <p className="line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">{source.description}</p>
                  ) : null}
                  <div className="grid grid-cols-4 gap-1.5">
                    <Count label="Documents" value={counts.documents} />
                    <Count label="Indexés" value={counts.indexed} className="text-emerald-700 dark:text-emerald-300" />
                    <Count
                      label="En cours"
                      value={counts.processing}
                      className={counts.processing > 0 ? "text-blue-700 dark:text-blue-300" : undefined}
                    />
                    <Count
                      label="Échecs"
                      value={counts.failed}
                      className={counts.failed > 0 ? "text-red-700 dark:text-red-300" : undefined}
                    />
                  </div>
                  {counts.documents > 0 ? (
                    <div className="grid gap-1">
                      <Progress
                        value={indexedRatio * 100}
                        tone={counts.failed > 0 ? "amber" : "teal"}
                        size="xs"
                        aria-label={`${formatPercent(indexedRatio)} des documents indexés`}
                      />
                      <span className="text-[11px] text-muted-foreground">{formatPercent(indexedRatio)} indexés</span>
                    </div>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-1.5">
                    <ClassificationBadge level={source.default_classification} prefix="Défaut" />
                    <AclChips principals={source.default_acl} members={members.data} max={2} />
                  </div>
                </div>

                <div className="flex items-center gap-2 border-t border-border px-4 py-2.5">
                  <Button
                    variant="ghost"
                    size="xs"
                    leftIcon={<FileStack aria-hidden />}
                    onClick={() => onShowDocuments(source.id)}
                    disabled={counts.documents === 0}
                  >
                    Voir les documents
                  </Button>
                  <RequireRole min="editor">
                    <Button
                      variant="ghost"
                      size="xs"
                      className="ml-auto"
                      leftIcon={<UploadCloud aria-hidden />}
                      onClick={() => setUploadSourceId(source.id)}
                    >
                      Ajouter
                    </Button>
                  </RequireRole>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <SourceDialog slug={slug} open={sourceDialogOpen} onOpenChange={setSourceDialogOpen} source={dialogSource} />
      <UploadDialog
        slug={slug}
        open={uploadSourceId !== null}
        onOpenChange={(open) => {
          if (!open) setUploadSourceId(null);
        }}
        defaultSourceId={uploadSourceId ?? undefined}
      />
    </div>
  );
}
