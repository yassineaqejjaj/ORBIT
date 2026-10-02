"use client";

import * as React from "react";
import Link from "next/link";
import { BellRing, Camera, CircleCheck, Mail, Newspaper, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { projectHref } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Label } from "@/components/ui/label";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CHANGE_TYPE_LABELS,
  CHANGE_TYPES,
  useDigest,
  useSinceSnapshot,
  useSubscription,
  useUpdateSubscription,
  type DigestFrequency,
  type DigestPeriod,
  type OutdatedItem,
} from "@/lib/api/features-feed";
import { useSnapshots, useSnapshotVersions } from "@/lib/api/hooks";
import { formatDateTime, plural } from "@/lib/format";
import { ChangeRow } from "./changes-timeline";

const OUTDATED_LABELS: Record<OutdatedItem["reason"], string> = {
  superseded: "Remplacé",
  forgotten: "Oublié",
  obsolete: "Obsolète",
  edited: "Modifié",
  new_version: "Nouvelle version",
  stale: "Périmé",
};

/** « Depuis le snapshot … » : what changed since a snapshot version and which of its items are outdated. */
export function SinceSnapshotCard({ slug }: { slug: string }) {
  const snapshots = useSnapshots(slug);
  const [name, setName] = React.useState<string | null>(null);
  const [version, setVersion] = React.useState<string>("latest");
  React.useEffect(() => {
    if (!name && snapshots.data?.length) setName(snapshots.data[0]?.name ?? null);
  }, [name, snapshots.data]);
  const versions = useSnapshotVersions(slug, name ?? undefined);
  const since = useSinceSnapshot(slug, name, version === "latest" ? "latest" : Number(version));

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <Camera className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Depuis le snapshot…</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {snapshots.isPending ? (
          <Skeleton className="h-9" />
        ) : !snapshots.data?.length ? (
          <EmptyState
            size="sm"
            variant="plain"
            icon={<Camera />}
            title="Aucun snapshot"
            description="Enregistrez un contexte en snapshot depuis l'explorateur pour suivre ce qui a changé depuis."
          />
        ) : (
          <>
            <div className="grid grid-cols-[minmax(0,1fr)_7rem] gap-2">
              <SimpleSelect
                size="sm"
                value={name ?? undefined}
                onValueChange={(value) => {
                  setName(value);
                  setVersion("latest");
                }}
                aria-label="Snapshot"
                options={snapshots.data.map((s) => ({ value: s.name, label: s.name }))}
              />
              <SimpleSelect
                size="sm"
                value={version}
                onValueChange={setVersion}
                aria-label="Version"
                options={[
                  { value: "latest", label: "Dernière" },
                  ...(versions.data ?? []).map((v) => ({ value: String(v.version), label: `v${v.version}` })),
                ]}
              />
            </div>
            {since.isPending ? (
              <Skeleton className="h-20" />
            ) : since.isError ? (
              <ErrorState size="sm" variant="plain" error={since.error} onRetry={() => void since.refetch()} />
            ) : (
              <div className="grid gap-2.5">
                <p className="text-xs text-muted-foreground">
                  « {since.data.snapshot.name} » v{since.data.snapshot.version} · {formatDateTime(since.data.snapshot.created_at)}
                  {" · "}
                  {plural(since.data.total, "changement", "changements")} depuis
                </p>
                {since.data.is_up_to_date ? (
                  <p className="flex items-center gap-2 rounded-lg border border-green-600/20 bg-green-50 px-3 py-2 text-[13px] text-green-900 dark:border-green-400/25 dark:bg-green-400/10 dark:text-green-100">
                    <CircleCheck className="size-4 shrink-0" aria-hidden />
                    Ce snapshot est toujours à jour.
                  </p>
                ) : (
                  <div className="grid gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-[13px] text-amber-950 dark:border-amber-400/35 dark:bg-amber-400/10 dark:text-amber-100">
                    <p className="flex items-center gap-2 font-medium">
                      <TriangleAlert className="size-4 shrink-0" aria-hidden />
                      Ce snapshot n&apos;est plus à jour
                    </p>
                    <ul className="grid gap-1.5">
                      {since.data.outdated.map((item) => (
                        <li key={`${item.item_type}-${item.id}`} className="grid gap-0.5">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <Badge tone="amber" size="sm">
                              {OUTDATED_LABELS[item.reason]}
                            </Badge>
                            <Link
                              href={
                                item.item_type === "memory"
                                  ? `${projectHref(slug, "memory")}?item=${encodeURIComponent(item.id)}`
                                  : `${projectHref(slug, "sources")}/${encodeURIComponent(item.id)}`
                              }
                              className="min-w-0 truncate font-medium hover:underline"
                            >
                              {item.title}
                            </Link>
                          </span>
                          <span className="text-xs opacity-90">{item.detail}</span>
                        </li>
                      ))}
                    </ul>
                    {since.data.hidden_outdated > 0 ? (
                      <p className="text-xs opacity-90">
                        {plural(since.data.hidden_outdated, "autre élément restreint", "autres éléments restreints")} hors de
                        votre habilitation.
                      </p>
                    ) : null}
                  </div>
                )}
                {since.data.changes.length ? (
                  <ol className="grid">
                    {since.data.changes.slice(0, 5).map((event) => (
                      <ChangeRow key={event.id} slug={slug} event={event} compact />
                    ))}
                  </ol>
                ) : null}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** Digest of the last day / week (also e-mailed by the worker when SMTP is configured). */
export function DigestCard({ slug }: { slug: string }) {
  const [period, setPeriod] = React.useState<DigestPeriod>("day");
  const digest = useDigest(slug, period);
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <Newspaper className="size-4 text-muted-foreground" aria-hidden />
        <CardTitle>Résumé</CardTitle>
        <CardAction>
          <SegmentedControl<DigestPeriod>
            size="sm"
            value={period}
            onValueChange={setPeriod}
            aria-label="Période du résumé"
            options={[
              { value: "day", label: "24 h" },
              { value: "week", label: "7 jours" },
            ]}
          />
        </CardAction>
      </CardHeader>
      <CardContent>
        {digest.isPending ? (
          <Skeleton className="h-24" />
        ) : digest.isError ? (
          <ErrorState size="sm" variant="plain" error={digest.error} onRetry={() => void digest.refetch()} />
        ) : digest.data.total === 0 ? (
          <p className="text-[13px] text-muted-foreground">Aucun changement sur la période.</p>
        ) : (
          <ul className="grid gap-1.5">
            {digest.data.groups.map((group) => (
              <li key={group.type} className="flex items-center justify-between gap-2 text-[13px]">
                <span className="truncate">{group.label}</span>
                <Badge tone="neutral" size="sm">
                  {group.count}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const FREQUENCY_OPTIONS: { value: DigestFrequency; label: string }[] = [
  { value: "off", label: "Désactivé" },
  { value: "daily", label: "Quotidien" },
  { value: "weekly", label: "Hebdomadaire" },
];

/** Personal subscription: digest frequency and followed change types. */
export function SubscriptionDialog({ slug, open, onOpenChange }: { slug: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const subscription = useSubscription(slug);
  const update = useUpdateSubscription(slug);
  const [digest, setDigest] = React.useState<DigestFrequency>("off");
  const [types, setTypes] = React.useState<string[]>([]);
  React.useEffect(() => {
    if (open && subscription.data) {
      setDigest(subscription.data.digest);
      setTypes(subscription.data.types);
    }
  }, [open, subscription.data]);
  const toggle = (type: string) => setTypes((prev) => (prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Mon abonnement</DialogTitle>
          <DialogDescription>
            Recevez un résumé des changements de ce projet, filtré selon vos droits d&apos;accès.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <p className="text-[13px] font-medium">Fréquence du résumé</p>
            <SegmentedControl<DigestFrequency>
              value={digest}
              onValueChange={setDigest}
              aria-label="Fréquence du résumé"
              options={FREQUENCY_OPTIONS}
            />
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Mail className="size-3.5" aria-hidden />
              {subscription.data?.email_enabled
                ? "Envoyé par e-mail à votre adresse de connexion."
                : "L'envoi d'e-mails n'est pas configuré sur cette instance : le résumé reste consultable sur cette page."}
            </p>
          </div>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-[13px] font-medium">Types suivis</legend>
            <p className="text-xs text-muted-foreground">Aucun type coché = tous les changements.</p>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {CHANGE_TYPES.map((type) => (
                <div key={type} className="flex items-center gap-2">
                  <Checkbox id={`sub-${type}`} checked={types.includes(type)} onCheckedChange={() => toggle(type)} />
                  <Label htmlFor={`sub-${type}`} className="text-[13px] font-normal">
                    {CHANGE_TYPE_LABELS[type]}
                  </Label>
                </div>
              ))}
            </div>
          </fieldset>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Annuler
          </Button>
          <Button
            disabled={update.isPending || subscription.isPending}
            onClick={() =>
              update
                .mutateAsync({ digest, types })
                .then(() => {
                  toast.success("Abonnement enregistré");
                  onOpenChange(false);
                })
                .catch(() => undefined)
            }
          >
            <BellRing aria-hidden />
            Enregistrer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
