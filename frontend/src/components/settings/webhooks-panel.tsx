"use client";

import * as React from "react";
import { History, KeyRound, Lock, Pencil, Plus, Send, ShieldAlert, Trash2, TriangleAlert, Webhook } from "lucide-react";
import { toast } from "sonner";

import { RelativeTime } from "@/components/domain/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { CodeBlock } from "@/components/ui/code-block";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Pagination } from "@/components/ui/pagination";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import {
  CHANGE_TYPE_LABELS,
  CHANGE_TYPES,
  useCreateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  useUpdateWebhook,
  useWebhookDeliveries,
  useWebhooks,
  type Webhook as WebhookRow,
  type WebhookCreated,
} from "@/lib/api/features-feed";
import { formatDateTime, formatMs } from "@/lib/format";

const VERIFY_SNIPPET = `import hashlib, hmac

def is_valid(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)  # header = X-Orbit-Signature`;

/** Owner-only management of outgoing webhooks (docs/FEATURES.md F2). */
export function WebhooksPanel() {
  const { slug, isOwner } = useCurrentProject();
  const webhooks = useWebhooks(slug, isOwner);
  const update = useUpdateWebhook(slug);
  const remove = useDeleteWebhook(slug);
  const test = useTestWebhook(slug);
  const [editing, setEditing] = React.useState<WebhookRow | "new" | null>(null);
  const [created, setCreated] = React.useState<WebhookCreated | null>(null);
  const [deleting, setDeleting] = React.useState<WebhookRow | null>(null);
  const [history, setHistory] = React.useState<WebhookRow | null>(null);

  if (!isOwner) {
    return (
      <EmptyState
        icon={<Lock />}
        title="Réservé aux propriétaires"
        description="Seuls les propriétaires du projet peuvent configurer les webhooks sortants."
      />
    );
  }

  const runTest = (hook: WebhookRow) =>
    test
      .mutateAsync(hook.id)
      .then((delivery) => {
        if (delivery.status === "succeeded") {
          toast.success("Événement de test livré", { description: `HTTP ${delivery.response_status} · ${formatMs(delivery.duration_ms)}` });
        } else {
          toast.error("Échec de la livraison de test", { description: delivery.error ?? undefined });
        }
      })
      .catch(() => undefined);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-start gap-3">
          <div className="grid flex-1 gap-1">
            <CardTitle>Webhooks sortants</CardTitle>
            <CardDescription>
              ORBIT envoie un POST JSON signé (HMAC-SHA256, en-tête <code>X-Orbit-Signature</code>) à chaque changement suivi.
              Les contenus C2+ ou restreints par ACL ne sont jamais transmis : seuls le type et les identifiants le sont.
            </CardDescription>
          </div>
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus aria-hidden />
            Ajouter un webhook
          </Button>
        </CardHeader>
        <CardContent>
          {webhooks.isPending ? (
            <div className="grid gap-2">
              <Skeleton className="h-20 rounded-lg" />
              <Skeleton className="h-20 rounded-lg" />
            </div>
          ) : webhooks.isError ? (
            <ErrorState error={webhooks.error} onRetry={() => void webhooks.refetch()} />
          ) : webhooks.data.length === 0 ? (
            <EmptyState
              size="sm"
              icon={<Webhook />}
              title="Aucun webhook"
              description="Notifiez un CRM, un outil de ticketing ou un canal de discussion quand une décision change."
            />
          ) : (
            <ul className="grid gap-2.5">
              {webhooks.data.map((hook) => (
                <li key={hook.id} className="grid gap-2 rounded-lg border border-border px-3.5 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Switch
                      checked={hook.enabled}
                      aria-label={hook.enabled ? "Désactiver le webhook" : "Activer le webhook"}
                      disabled={update.isPending}
                      onCheckedChange={(enabled) => void update.mutateAsync({ id: hook.id, enabled }).catch(() => undefined)}
                    />
                    <code className="min-w-0 flex-1 truncate text-[13px] font-medium">{hook.url}</code>
                    {hook.last_status ? (
                      <Badge tone={hook.last_status === "succeeded" ? "green" : "red"} size="sm" dot>
                        {hook.last_status === "succeeded" ? "Dernière livraison réussie" : "Dernière livraison en échec"}
                      </Badge>
                    ) : (
                      <Badge tone="neutral" size="sm">
                        Jamais déclenché
                      </Badge>
                    )}
                  </div>
                  {hook.description ? <p className="text-xs text-muted-foreground">{hook.description}</p> : null}
                  <div className="flex flex-wrap gap-1">
                    {hook.types.length === 0 ? (
                      <Badge tone="blue" size="sm">
                        Tous les changements
                      </Badge>
                    ) : (
                      hook.types.map((type) => (
                        <Badge key={type} tone="neutral" size="sm">
                          {CHANGE_TYPE_LABELS[type as keyof typeof CHANGE_TYPE_LABELS] ?? type}
                        </Badge>
                      ))
                    )}
                  </div>
                  {hook.disabled_reason ? (
                    <p className="flex items-start gap-2 rounded-md border border-red-300/70 bg-red-50 px-2.5 py-2 text-xs text-red-900 dark:border-red-400/30 dark:bg-red-400/10 dark:text-red-100">
                      <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                      {hook.disabled_reason}
                    </p>
                  ) : hook.consecutive_failures > 0 ? (
                    <p className="text-xs text-amber-700 dark:text-amber-300">
                      {hook.consecutive_failures} échec(s) consécutif(s) — désactivation automatique au-delà du seuil.
                    </p>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <KeyRound className="size-3.5" aria-hidden />
                    <span className="font-mono">{hook.secret_hint}</span>
                    {hook.last_delivery_at ? (
                      <span>
                        · dernière livraison <RelativeTime date={hook.last_delivery_at} />
                      </span>
                    ) : null}
                    <div className="ml-auto flex flex-wrap gap-1">
                      <Button size="xs" variant="ghost" onClick={() => void runTest(hook)} disabled={test.isPending}>
                        <Send aria-hidden />
                        Tester
                      </Button>
                      <Button size="xs" variant="ghost" onClick={() => setHistory(hook)}>
                        <History aria-hidden />
                        Livraisons
                      </Button>
                      <Button size="xs" variant="ghost" onClick={() => setEditing(hook)}>
                        <Pencil aria-hidden />
                        Modifier
                      </Button>
                      <Button size="xs" variant="ghost" className="text-destructive" onClick={() => setDeleting(hook)}>
                        <Trash2 aria-hidden />
                        Supprimer
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <WebhookFormDialog
        slug={slug}
        value={editing}
        onClose={() => setEditing(null)}
        onCreated={(result) => {
          setEditing(null);
          setCreated(result);
        }}
      />
      <SecretDialog created={created} onClose={() => setCreated(null)} />
      <DeliveriesSheet slug={slug} hook={history} onClose={() => setHistory(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Supprimer ce webhook ?"
        description={deleting ? `Plus aucun événement ne sera envoyé à ${deleting.url}. L'historique des livraisons est supprimé.` : undefined}
        confirmLabel="Supprimer"
        destructive
        loading={remove.isPending}
        onConfirm={() =>
          deleting
            ? remove
                .mutateAsync(deleting.id)
                .then(() => {
                  toast.success("Webhook supprimé");
                  setDeleting(null);
                })
                .catch(() => undefined)
            : undefined
        }
      />
    </div>
  );
}

function WebhookFormDialog({
  slug,
  value,
  onClose,
  onCreated,
}: {
  slug: string;
  value: WebhookRow | "new" | null;
  onClose: () => void;
  onCreated: (created: WebhookCreated) => void;
}) {
  const create = useCreateWebhook(slug);
  const update = useUpdateWebhook(slug);
  const editing = value && value !== "new" ? value : null;
  const [url, setUrl] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [types, setTypes] = React.useState<string[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (value === null) return;
    setUrl(editing?.url ?? "");
    setDescription(editing?.description ?? "");
    setTypes(editing?.types ?? []);
    setError(null);
  }, [value, editing]);
  const toggle = (type: string) => setTypes((prev) => (prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]));
  const pending = create.isPending || update.isPending;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const body = { url: url.trim(), description: description.trim(), types };
    const action = editing
      ? update.mutateAsync({ id: editing.id, ...body }).then(() => {
          toast.success("Webhook modifié");
          onClose();
        })
      : create.mutateAsync(body).then(onCreated);
    action.catch((err) => setError(errorMessage(err)));
  };

  return (
    <Dialog open={value !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{editing ? "Modifier le webhook" : "Nouveau webhook"}</DialogTitle>
            <DialogDescription>
              URL HTTPS publique uniquement : les adresses privées, loopback et link-local sont refusées (protection anti-SSRF).
            </DialogDescription>
          </DialogHeader>
          <Field id="webhook-url" label="URL de destination" required error={error ?? undefined}>
            <Input
              id="webhook-url"
              type="url"
              required
              placeholder="https://exemple.fr/hooks/orbit"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              autoFocus
            />
          </Field>
          <Field id="webhook-description" label="Description" hint="Facultatif — ex. « Synchronisation CRM »">
            <Input
              id="webhook-description"
              maxLength={500}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-[13px] font-medium">Événements</legend>
            <p className="text-xs text-muted-foreground">Aucun type coché = tous les changements.</p>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {CHANGE_TYPES.map((type) => (
                <div key={type} className="flex items-center gap-2">
                  <Checkbox id={`wh-${type}`} checked={types.includes(type)} onCheckedChange={() => toggle(type)} />
                  <Label htmlFor={`wh-${type}`} className="text-[13px] font-normal">
                    {CHANGE_TYPE_LABELS[type]}
                  </Label>
                </div>
              ))}
            </div>
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Annuler
            </Button>
            <Button type="submit" disabled={pending || !url.trim()}>
              {editing ? "Enregistrer" : "Créer le webhook"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The signing secret is shown exactly once. */
function SecretDialog({ created, onClose }: { created: WebhookCreated | null; onClose: () => void }) {
  const [acknowledged, setAcknowledged] = React.useState(false);
  React.useEffect(() => {
    if (created) setAcknowledged(false);
  }, [created]);
  return (
    <Dialog open={created !== null} onOpenChange={(open) => !open && acknowledged && onClose()}>
      <DialogContent
        size="lg"
        hideClose
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => {
          if (!acknowledged) e.preventDefault();
        }}
      >
        {created ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Webhook créé</DialogTitle>
              <DialogDescription className="break-all">{created.url}</DialogDescription>
            </DialogHeader>
            <div
              role="alert"
              className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3.5 py-3 text-[13px] text-amber-950 dark:border-amber-400/35 dark:bg-amber-400/10 dark:text-amber-100"
            >
              <ShieldAlert className="mt-px size-4 shrink-0" aria-hidden />
              <p className="leading-relaxed">
                <strong className="font-semibold">Copiez ce secret maintenant : il ne sera plus jamais affiché.</strong> Il
                sert à vérifier la signature <code>X-Orbit-Signature</code> de chaque livraison.
              </p>
            </div>
            <CodeBlock code={created.secret} title="Secret de signature" wrap maxHeightClassName="max-h-24" />
            <CodeBlock code={VERIFY_SNIPPET} language="python" title="Vérifier la signature" maxHeightClassName="max-h-48" />
            <DialogFooter className="items-stretch sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Checkbox id="wh-secret-ack" checked={acknowledged} onCheckedChange={(c) => setAcknowledged(c === true)} />
                <Label htmlFor="wh-secret-ack" className="text-[13px] font-normal">
                  J&apos;ai copié le secret et je l&apos;ai stocké en lieu sûr
                </Label>
              </div>
              <Button onClick={onClose} disabled={!acknowledged}>
                Terminer
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

const DELIVERY_STATUS: Record<string, { label: string; tone: "green" | "red" | "amber" | "neutral" }> = {
  succeeded: { label: "Livrée", tone: "green" },
  failed: { label: "Échec", tone: "red" },
  pending: { label: "En attente", tone: "amber" },
  skipped: { label: "Abandonnée", tone: "neutral" },
};

function DeliveriesSheet({ slug, hook, onClose }: { slug: string; hook: WebhookRow | null; onClose: () => void }) {
  const [page, setPage] = React.useState(1);
  React.useEffect(() => setPage(1), [hook?.id]);
  const deliveries = useWebhookDeliveries(slug, hook?.id ?? null, page);
  return (
    <Sheet open={hook !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Livraisons</SheetTitle>
          <SheetDescription className="break-all">{hook?.url}</SheetDescription>
        </SheetHeader>
        <SheetBody className="grid content-start gap-2">
          {deliveries.isPending ? (
            <Skeleton className="h-32" />
          ) : deliveries.isError ? (
            <ErrorState size="sm" error={deliveries.error} onRetry={() => void deliveries.refetch()} />
          ) : deliveries.data.items.length === 0 ? (
            <EmptyState size="sm" variant="plain" icon={<Send />} title="Aucune livraison" />
          ) : (
            <>
              <ul className="grid gap-2">
                {deliveries.data.items.map((d) => {
                  const status = DELIVERY_STATUS[d.status] ?? DELIVERY_STATUS.pending!;
                  return (
                    <li key={d.id} className="grid gap-1 rounded-lg border border-border px-3 py-2 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={status.tone} size="sm" dot>
                          {status.label}
                        </Badge>
                        <code className="font-medium">{d.event_type}</code>
                        <span className="ml-auto text-muted-foreground">{formatDateTime(d.created_at)}</span>
                      </div>
                      <p className="text-muted-foreground">
                        {d.attempts} tentative(s)
                        {d.response_status ? ` · HTTP ${d.response_status}` : ""}
                        {d.duration_ms !== null ? ` · ${formatMs(d.duration_ms)}` : ""}
                      </p>
                      {d.error ? <p className="text-red-700 dark:text-red-300">{d.error}</p> : null}
                    </li>
                  );
                })}
              </ul>
              <Pagination
                page={page}
                pageSize={20}
                total={deliveries.data.total}
                onPageChange={setPage}
                compact
                disabled={deliveries.isFetching}
              />
            </>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
