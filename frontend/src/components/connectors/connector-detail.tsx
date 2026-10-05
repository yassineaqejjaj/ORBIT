"use client";

import * as React from "react";
import Link from "next/link";
import { FileText, Pause, Pencil, Play, PlugZap, RefreshCw, Telescope, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { projectHref } from "@/components/layout/nav";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect } from "@/components/ui/select";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import {
  isRunActive,
  useConnector,
  useConnectorRuns,
  useDeleteConnector,
  useSyncConnector,
  useConnectorTypes,
  useTestSavedConnector,
  useUpdateConnector,
  type Connector,
  type ConnectorConfig,
  type ConnectorPatch,
} from "@/lib/api/features-connectors";
import { CLASSIFICATION_META, CLASSIFICATIONS } from "@/lib/enums";
import { formatDateTime, formatMs, formatNumber } from "@/lib/format";
import {
  CONNECTOR_STATUS_META,
  RUN_TRIGGER_LABELS,
  SCHEDULE_OPTIONS,
  scheduleLabel,
  scopeLabelFor,
  scopeSummary,
} from "./connector-meta";
import { McpFieldInputs } from "./mcp-fields";
import { ConnectorTypeIcon, McpBadge, RunProgress, RunStatusBadge } from "./run-stats";

export function ConnectorStatusBadge({ connector }: { connector: Connector }) {
  const active = isRunActive(connector.last_run);
  const meta = CONNECTOR_STATUS_META[active && !connector.paused ? "syncing" : connector.status];
  return (
    <Badge tone={meta.tone} size="sm" dot pulse={active}>
      {meta.label}
    </Badge>
  );
}

/** Connector detail sheet: settings summary, actions and run history. */
export function ConnectorDetailSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { slug, canEdit, isOwner } = useCurrentProject();
  const connector = useConnector(slug, id);
  const [page, setPage] = React.useState(1);
  const live = isRunActive(connector.data?.last_run);
  const runs = useConnectorRuns(slug, id, page, live);
  const sync = useSyncConnector(slug);
  const test = useTestSavedConnector(slug);
  const update = useUpdateConnector(slug);
  const remove = useDeleteConnector(slug);
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);

  React.useEffect(() => setPage(1), [id]);
  const data = connector.data;

  const runSync = () =>
    data &&
    sync
      .mutateAsync(data.id)
      .then(() => toast.success("Synchronisation lancée"))
      .catch(() => undefined);
  const runTest = () =>
    data &&
    test
      .mutateAsync({ id: data.id })
      .then((result) => {
        const description = result.tools.length ? `${result.message} (${result.tools.length} outils MCP)` : result.message;
        return result.ok ? toast.success("Connexion réussie", { description }) : toast.error("Échec du test", { description });
      })
      .catch(() => undefined);
  const togglePause = () =>
    data &&
    update
      .mutateAsync({ id: data.id, paused: !data.paused })
      .then((next) => toast.success(next.paused ? "Synchronisation automatique suspendue" : "Synchronisation automatique reprise"))
      .catch((err) => toast.error(errorMessage(err)));

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent size="xl">
        {connector.isPending ? (
          <div className="grid gap-3 p-6">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-40 rounded-lg" />
            <Skeleton className="h-64 rounded-lg" />
          </div>
        ) : connector.isError ? (
          <div className="p-6">
            <ErrorState error={connector.error} onRetry={() => void connector.refetch()} />
          </div>
        ) : data ? (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <ConnectorTypeIcon type={data.type} preset={data.preset} className="size-5 text-primary" />
                {data.name}
              </SheetTitle>
              <SheetDescription className="flex flex-wrap items-center gap-2">
                {data.via_mcp ? <McpBadge /> : null}
                <span>{data.type_label}</span>
                <ConnectorStatusBadge connector={data} />
              </SheetDescription>
            </SheetHeader>
            <SheetBody className="grid gap-5">
              <div className="flex flex-wrap gap-2">
                {canEdit ? (
                  <Button size="sm" onClick={runSync} loading={sync.isPending} disabled={live}>
                    <RefreshCw aria-hidden />
                    Synchroniser
                  </Button>
                ) : null}
                {isOwner ? (
                  <>
                    <Button size="sm" variant="secondary" onClick={runTest} loading={test.isPending}>
                      <PlugZap aria-hidden />
                      Tester les identifiants
                    </Button>
                    <Button size="sm" variant="secondary" onClick={togglePause} disabled={update.isPending}>
                      {data.paused ? <Play aria-hidden /> : <Pause aria-hidden />}
                      {data.paused ? "Reprendre" : "Suspendre"}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                      <Pencil aria-hidden />
                      Modifier
                    </Button>
                    <Button size="sm" variant="destructive-outline" onClick={() => setDeleting(true)}>
                      <Trash2 aria-hidden />
                      Supprimer
                    </Button>
                  </>
                ) : null}
                {data.document_count > 0 ? (
                  <Button size="sm" variant="ghost" asChild>
                    <Link href={`${projectHref(slug, "explorer")}?task=${encodeURIComponent(data.suggested_task)}`}>
                      <Telescope aria-hidden />
                      Explorer le contexte
                    </Link>
                  </Button>
                ) : null}
              </div>

              {data.last_error ? <Alert tone={data.status === "error" ? "red" : "amber"}>{data.last_error}</Alert> : null}

              <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                <Info label={scopeLabelFor(data.type)}>{scopeSummary(data.type, data.config)}</Info>
                <Info label="Planification">{scheduleLabel(data.schedule_minutes)}</Info>
                <Info label="Classification par défaut">
                  <ClassificationBadge level={data.default_classification} />
                </Info>
                <Info label="Droits">
                  <code className="text-xs">{data.acl_principals.join(", ")}</code>
                  {data.restrict_to_editors ? " · éditeurs uniquement" : " · tout le projet"}
                </Info>
                <Info label="Documents synchronisés">
                  <span className="inline-flex items-center gap-1">
                    <FileText className="size-3.5 text-muted-foreground" aria-hidden />
                    {formatNumber(data.document_count, 0)}
                  </span>
                </Info>
                <Info label="Dernière synchronisation">
                  {data.last_sync_at ? <RelativeTime date={data.last_sync_at} /> : "Jamais"}
                </Info>
                <Info label="Secret">
                  <code className="text-xs">{data.has_secret ? data.secret_hint : "Absent"}</code>
                </Info>
                {data.config.base_url ? (
                  <Info label="URL">
                    <span className="break-all">{data.config.base_url}</span>
                  </Info>
                ) : null}
              </dl>

              {live && data.last_run ? (
                <section className="grid gap-2 rounded-lg border border-border p-3.5">
                  <h3 className="text-sm font-medium">Synchronisation en cours</h3>
                  <RunProgress run={data.last_run} />
                </section>
              ) : null}

              <section className="grid gap-2">
                <h3 className="text-sm font-medium">Historique des synchronisations</h3>
                {runs.isPending ? (
                  <Skeleton className="h-40 rounded-lg" />
                ) : runs.isError ? (
                  <ErrorState error={runs.error} onRetry={() => void runs.refetch()} size="sm" />
                ) : runs.data.items.length === 0 ? (
                  <EmptyState size="sm" icon={<RefreshCw />} title="Aucune synchronisation" description="Lancez la première synchronisation pour importer les contenus." />
                ) : (
                  <>
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Date</TableHead>
                            <TableHead>Déclencheur</TableHead>
                            <TableHead>Statut</TableHead>
                            <TableHead className="text-right">Récupérés</TableHead>
                            <TableHead className="text-right">Créés</TableHead>
                            <TableHead className="text-right">Mis à jour</TableHead>
                            <TableHead className="text-right">Oubliés</TableHead>
                            <TableHead className="text-right">Erreurs</TableHead>
                            <TableHead className="text-right">Durée</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {runs.data.items.map((run) => (
                            <TableRow key={run.id} title={run.error ?? undefined}>
                              <TableCell className="whitespace-nowrap">{formatDateTime(run.created_at)}</TableCell>
                              <TableCell>{RUN_TRIGGER_LABELS[run.trigger]}</TableCell>
                              <TableCell>
                                <RunStatusBadge run={run} />
                              </TableCell>
                              <TableCell className="text-right tabular-nums">{run.fetched}</TableCell>
                              <TableCell className="text-right tabular-nums">{run.created}</TableCell>
                              <TableCell className="text-right tabular-nums">{run.updated}</TableCell>
                              <TableCell className="text-right tabular-nums">{run.forgotten}</TableCell>
                              <TableCell className="text-right tabular-nums">{run.errors}</TableCell>
                              <TableCell className="text-right whitespace-nowrap">{formatMs(run.duration_ms)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    <Pagination page={page} pageSize={runs.data.page_size} total={runs.data.total} onPageChange={setPage} />
                  </>
                )}
              </section>
            </SheetBody>

            <EditConnectorDialog connector={data} open={editing} onClose={() => setEditing(false)} />
            <ConfirmDialog
              open={deleting}
              onOpenChange={setDeleting}
              destructive
              title={`Supprimer « ${data.name} » ?`}
              description="Le connecteur et ses identifiants sont supprimés. Les documents déjà synchronisés restent dans le projet (utilisez l'oubli sélectif pour les retirer)."
              confirmLabel="Supprimer"
              loading={remove.isPending}
              onConfirm={() =>
                remove.mutateAsync(data.id).then(() => {
                  toast.success("Connecteur supprimé");
                  setDeleting(false);
                  onClose();
                })
              }
            />
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function splitList(value: string): string[] {
  return value
    .split(/[\s,;]+/)
    .map((v) => v.trim())
    .filter(Boolean);
}

/** Owner settings: name, schedule, classification/ACL, scope and secret rotation. */
function EditConnectorDialog({ connector, open, onClose }: { connector: Connector; open: boolean; onClose: () => void }) {
  const { slug } = useCurrentProject();
  const update = useUpdateConnector(slug);
  const [name, setName] = React.useState(connector.name);
  const [schedule, setSchedule] = React.useState(String(connector.schedule_minutes));
  const [classification, setClassification] = React.useState(connector.default_classification);
  const [restrict, setRestrict] = React.useState(connector.restrict_to_editors);
  const [scope, setScope] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const isMcp = connector.type === "mcp";
  const types = useConnectorTypes(slug, open && isMcp);
  const preset = types.data?.find((t) => t.via_mcp && t.preset === connector.preset) ?? null;
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [mcpSecrets, setMcpSecrets] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    if (!open) return;
    setName(connector.name);
    setSchedule(String(connector.schedule_minutes));
    setClassification(connector.default_classification);
    setRestrict(connector.restrict_to_editors);
    const c = connector.config;
    setScope(
      connector.type === "jira" ? (c.jql ?? "") : connector.type === "confluence" ? (c.space_keys ?? []).join(", ") : (c.drive_ids ?? []).join(", "),
    );
    setSecret("");
    setValues({ ...connector.config });
    setMcpSecrets({});
    setError(null);
  }, [open, connector]);

  const scheduleOptions = SCHEDULE_OPTIONS.some((o) => o.value === String(connector.schedule_minutes))
    ? SCHEDULE_OPTIONS
    : [...SCHEDULE_OPTIONS, { value: String(connector.schedule_minutes), label: scheduleLabel(connector.schedule_minutes) }];

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const c = connector.config;
    let config: ConnectorConfig | undefined;
    if (connector.type === "jira" && scope.trim() !== (c.jql ?? "")) config = { ...c, jql: scope.trim() };
    if (connector.type === "confluence" && scope !== (c.space_keys ?? []).join(", ")) {
      config = { ...c, space_keys: splitList(scope), scope_labels: splitList(scope) };
    }
    if (connector.type === "sharepoint" && scope !== (c.drive_ids ?? []).join(", ")) {
      config = { ...c, drive_ids: splitList(scope), scope_labels: undefined };
    }
    let secretValue = secret;
    if (isMcp) {
      const strip = (o: Record<string, unknown>) =>
        JSON.stringify(Object.fromEntries(Object.entries(o).filter(([k]) => k !== "preset" && k !== "scope_labels")));
      if (strip(values) !== strip(c)) config = { ...values } as ConnectorConfig;
      const filled = Object.fromEntries(Object.entries(mcpSecrets).filter(([, v]) => v.trim() !== ""));
      secretValue = Object.keys(filled).length ? JSON.stringify(filled) : "";
    }
    const body: ConnectorPatch = {
      name: name.trim(),
      schedule_minutes: Number(schedule),
      default_classification: classification,
      restrict_to_editors: restrict,
      ...(config ? { config } : {}),
      ...(secretValue ? { secret: secretValue } : {}),
    };
    update
      .mutateAsync({ id: connector.id, ...body })
      .then(() => {
        toast.success("Connecteur modifié");
        onClose();
      })
      .catch((err) => setError(errorMessage(err)));
  };

  const scopeLabel = scopeLabelFor(connector.type);
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Modifier le connecteur</DialogTitle>
            <DialogDescription>
              Changer le périmètre relance une synchronisation complète. La classification et les droits s&apos;appliquent aux
              prochains contenus synchronisés.
            </DialogDescription>
          </DialogHeader>
          <Field id="edit-name" label="Nom" required>
            <Input id="edit-name" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          {isMcp ? (
            preset ? (
              <McpFieldInputs
                fields={preset.fields}
                groups={["connection", "scope"]}
                values={values}
                secrets={mcpSecrets}
                onValue={(key, value) => setValues((v) => ({ ...v, [key]: value }))}
                onSecret={() => undefined}
                idPrefix="edit-mcp"
              />
            ) : types.isLoading ? (
              <Skeleton className="h-24 rounded-lg" />
            ) : (
              <Alert tone="amber">Préréglage MCP « {connector.preset} » indisponible sur cette instance.</Alert>
            )
          ) : (
          <Field
            id="edit-scope"
            label={connector.type === "sharepoint" ? "Identifiants des bibliothèques" : scopeLabel}
            hint={connector.type === "jira" ? "Sans ORDER BY" : "Séparés par des virgules"}
          >
            <Textarea id="edit-scope" rows={2} value={scope} onChange={(e) => setScope(e.target.value)} className="font-mono text-[13px]" />
          </Field>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="edit-schedule" label="Synchronisation automatique">
              <SimpleSelect id="edit-schedule" value={schedule} onValueChange={setSchedule} options={scheduleOptions.map((o) => ({ value: o.value, label: o.label }))} />
            </Field>
            <Field id="edit-classification" label="Classification par défaut">
              <SimpleSelect
                id="edit-classification"
                value={String(classification)}
                onValueChange={(v) => setClassification(Number(v))}
                options={CLASSIFICATIONS.map((level) => ({
                  value: String(level),
                  label: `${CLASSIFICATION_META[level].code} · ${CLASSIFICATION_META[level].label}`,
                }))}
              />
            </Field>
          </div>
          <div className="flex items-center gap-3">
            <Switch id="edit-restrict" checked={restrict} onCheckedChange={setRestrict} />
            <Label htmlFor="edit-restrict">Restreindre aux éditeurs</Label>
          </div>
          {isMcp && preset ? (
            <div className="grid gap-1.5">
              <p className="text-xs text-muted-foreground">
                Nouveaux identifiants (tous les champs requis) — laisser vide pour conserver les actuels (
                {connector.secret_hint || "absents"}).
              </p>
              <McpFieldInputs
                fields={preset.fields}
                groups={["secret"]}
                values={values}
                secrets={mcpSecrets}
                onValue={() => undefined}
                onSecret={(key, value) => setMcpSecrets((v) => ({ ...v, [key]: value }))}
                idPrefix="edit-mcp"
                optionalSecrets
              />
            </div>
          ) : !isMcp ? (
            <Field id="edit-secret" label="Nouveau secret" hint={`Laisser vide pour conserver le secret actuel (${connector.secret_hint || "absent"}).`}>
              <Input id="edit-secret" type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} />
            </Field>
          ) : null}
          {error ? <Alert tone="red">{error}</Alert> : null}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Annuler
            </Button>
            <Button type="submit" loading={update.isPending} disabled={!name.trim()}>
              Enregistrer
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
