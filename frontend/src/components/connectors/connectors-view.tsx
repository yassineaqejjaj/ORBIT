"use client";

import * as React from "react";
import { ChevronRight, FileText, PlugZap, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { useUrlParams } from "@/components/sources/use-url-params";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/hooks/use-current-project";
import { isRunActive, useConnectors, useSyncConnector, type Connector, type NativeConnectorType } from "@/lib/api/features-connectors";
import { formatNumber } from "@/lib/format";
import { ConnectorDetailSheet, ConnectorStatusBadge } from "./connector-detail";
import { CONNECTOR_TYPE_ORDER, CONNECTOR_TYPES, scheduleLabel, scopeSummary } from "./connector-meta";
import { ConnectorWizard } from "./connector-wizard";
import { ConnectorTypeIcon, McpBadge } from "./run-stats";

const WIZARD_TYPES = new Set<string>(CONNECTOR_TYPE_ORDER);

/** « Connecteurs » (docs/FEATURES.md F5): list, detail with runs, manual sync and the onboarding wizard. */
export function ConnectorsView() {
  const { slug, project, isOwner, canEdit } = useCurrentProject();
  const { get, set } = useUrlParams();
  const connectors = useConnectors(slug);
  const sync = useSyncConnector(slug);
  const selected = get("connector");
  const wizardParam = get("wizard");
  const wizardOpen = wizardParam !== null && isOwner;
  const wizardType = wizardParam && WIZARD_TYPES.has(wizardParam) ? (wizardParam as NativeConnectorType) : null;

  const openWizard = (type?: NativeConnectorType) => set({ wizard: type ?? "1", connector: null });
  const runSync = (connector: Connector) =>
    sync
      .mutateAsync(connector.id)
      .then(() => toast.success(`Synchronisation de « ${connector.name} » lancée`))
      .catch(() => undefined);

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        icon={<PlugZap />}
        eyebrow={project.name}
        title="Connecteurs"
        description="Synchronisez SharePoint/OneDrive, Confluence et Jira : les contenus passent par le pipeline d'ingestion gouverné (classification, ACL, caviardage PII) et restent à jour automatiquement."
        actions={
          isOwner ? (
            <Button size="sm" onClick={() => openWizard()}>
              <Plus aria-hidden />
              Ajouter un connecteur
            </Button>
          ) : null
        }
      />

      {connectors.isPending ? (
        <div className="grid gap-3 md:grid-cols-2" aria-busy="true" aria-label="Chargement des connecteurs">
          <Skeleton className="h-36 rounded-xl" />
          <Skeleton className="h-36 rounded-xl" />
        </div>
      ) : connectors.isError ? (
        <ErrorState error={connectors.error} onRetry={() => void connectors.refetch()} size="lg" />
      ) : connectors.data.length === 0 ? (
        <EmptyState
          size="lg"
          variant="card"
          icon={<PlugZap />}
          title="Aucun connecteur"
          description={
            isOwner
              ? "Connectez vos premières sources : l'assistant teste vos identifiants, vous choisissez le périmètre et la première synchronisation démarre aussitôt."
              : "Aucun connecteur n'est configuré. Demandez à un propriétaire du projet d'en ajouter un."
          }
          action={
            isOwner ? (
              <div className="flex flex-wrap justify-center gap-2">
                {CONNECTOR_TYPE_ORDER.map((type) => (
                  <Button key={type} variant={type === "sharepoint" ? "primary" : "secondary"} size="sm" onClick={() => openWizard(type)}>
                    <ConnectorTypeIcon type={type} />
                    {CONNECTOR_TYPES[type].label}
                  </Button>
                ))}
              </div>
            ) : null
          }
        />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {connectors.data.map((connector) => {
            const active = isRunActive(connector.last_run);
            return (
              <li key={connector.id}>
                <Card className="grid h-full gap-3 p-4">
                  <div className="flex items-start gap-3">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <ConnectorTypeIcon type={connector.type} preset={connector.preset} className="size-5" />
                    </span>
                    <div className="grid min-w-0 flex-1 gap-0.5">
                      <button
                        type="button"
                        className="truncate text-left font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => set({ connector: connector.id })}
                      >
                        {connector.name}
                      </button>
                      <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                        {connector.via_mcp ? <McpBadge /> : null}
                        <span className="truncate">
                          {connector.type_label} · {scopeSummary(connector.type, connector.config)}
                        </span>
                      </span>
                    </div>
                    <ConnectorStatusBadge connector={connector} />
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <FileText className="size-3.5" aria-hidden />
                      {formatNumber(connector.document_count, 0)} document(s)
                    </span>
                    <span aria-hidden>·</span>
                    <span>
                      {connector.last_sync_at ? (
                        <>
                          Synchronisé <RelativeTime date={connector.last_sync_at} />
                        </>
                      ) : (
                        "Jamais synchronisé"
                      )}
                    </span>
                    <span aria-hidden>·</span>
                    <span>{connector.paused ? "Planification suspendue" : scheduleLabel(connector.schedule_minutes)}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <ClassificationBadge level={connector.default_classification} />
                    {connector.restrict_to_editors ? (
                      <Badge tone="violet" size="sm">
                        Éditeurs uniquement
                      </Badge>
                    ) : null}
                    {connector.last_error ? (
                      <Badge tone="red" size="sm" className="max-w-full truncate" title={connector.last_error}>
                        {connector.last_error}
                      </Badge>
                    ) : null}
                  </div>
                  <div className="mt-auto flex flex-wrap justify-end gap-2">
                    {canEdit ? (
                      <Button size="xs" variant="secondary" onClick={() => runSync(connector)} disabled={active || sync.isPending}>
                        <RefreshCw aria-hidden className={active ? "animate-spin" : undefined} />
                        {active ? "En cours…" : "Synchroniser"}
                      </Button>
                    ) : null}
                    <Button size="xs" variant="ghost" onClick={() => set({ connector: connector.id })}>
                      Détails
                      <ChevronRight aria-hidden />
                    </Button>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      <ConnectorDetailSheet id={selected} onClose={() => set({ connector: null })} />
      <ConnectorWizard slug={slug} open={wizardOpen} initialType={wizardType} onClose={() => set({ wizard: null })} />
    </div>
  );
}
