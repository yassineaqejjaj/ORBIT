"use client";

import * as React from "react";
import { Link2, Plus, Trash2, Unplug } from "lucide-react";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/code-block";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api/client";
import {
  type TeamsUserLink,
  useDeleteTeamsIntegration,
  useSaveTeamsIntegration,
  useTeamsIntegration,
} from "@/lib/api/features-ask";
import { useMembers } from "@/lib/api/hooks";

export interface TeamsPanelProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Owner-only « Connecter Microsoft Teams »: outgoing-webhook token (stored encrypted) and account mapping. */
export function TeamsPanel({ slug, open, onOpenChange }: TeamsPanelProps) {
  const { data, isLoading, error, refetch } = useTeamsIntegration(slug, open);
  const members = useMembers(slug, { enabled: open });
  const save = useSaveTeamsIntegration(slug);
  const disconnect = useDeleteTeamsIntegration(slug);

  const [secret, setSecret] = React.useState("");
  const [appUrl, setAppUrl] = React.useState("");
  const [enabled, setEnabled] = React.useState(true);
  const [links, setLinks] = React.useState<TeamsUserLink[]>([]);

  React.useEffect(() => {
    if (!data) return;
    setEnabled(data.configured ? data.enabled : true);
    setAppUrl(data.app_url || (typeof window !== "undefined" ? window.location.origin : ""));
    setLinks(data.user_mapping.map(({ teams_id, user_id }) => ({ teams_id, user_id })));
    setSecret("");
  }, [data]);

  const webhookUrl = data && typeof window !== "undefined" ? `${window.location.origin}${data.webhook_path}` : "";
  const memberOptions = (members.data ?? []).map((m) => ({
    value: m.user.id,
    label: m.user.full_name || m.user.email,
    description: m.user.email,
  }));
  const validLinks = links.filter((l) => l.teams_id.trim() && l.user_id);

  const onSave = () =>
    save.mutate(
      { secret: secret.trim() || null, enabled, app_url: appUrl.trim() || null, user_mapping: validLinks },
      {
        onSuccess: () => toast.success("Microsoft Teams est connecté au projet"),
        onError: (e) => toast.error(errorMessage(e)),
      },
    );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="lg">
        <SheetHeader>
          <SheetTitle>Connecter Microsoft Teams</SheetTitle>
          <SheetDescription>
            Un webhook sortant Teams permet de mentionner ORBIT dans un canal. Chaque message est vérifié par signature
            HMAC et répond avec les mêmes règles de gouvernance que l&apos;application.
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-5">
          {isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-28 w-full" />
            </div>
          ) : error ? (
            <ErrorState error={error} onRetry={() => void refetch()} size="sm" />
          ) : data ? (
            <>
              {!data.encryption_available ? (
                <Alert tone="red" title="Chiffrement non configuré">
                  Définissez <code>ORBIT_ENCRYPTION_KEY</code> (clé Fernet) sur le serveur : le jeton Teams n&apos;est jamais
                  stocké en clair, la connexion est refusée tant que la clé manque.
                </Alert>
              ) : null}

              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium">État</span>
                {data.configured ? (
                  <Badge tone={data.enabled ? "green" : "neutral"} dot>
                    {data.enabled ? "Connecté" : "Suspendu"}
                  </Badge>
                ) : (
                  <Badge tone="neutral">Non connecté</Badge>
                )}
              </div>

              <ol className="list-decimal space-y-1.5 pl-5 text-[13px] text-muted-foreground">
                <li>Dans Teams : Gérer l&apos;équipe → Applications → Créer un webhook sortant.</li>
                <li>Collez l&apos;URL de rappel ci-dessous, puis copiez le jeton de sécurité affiché par Teams.</li>
                <li>Reliez chaque compte Teams (aadObjectId ou e-mail) à un membre du projet.</li>
              </ol>

              <Field id="teams-webhook" label="URL de rappel (callback)">
                <div className="flex items-center gap-2">
                  <Input id="teams-webhook" readOnly value={webhookUrl} className="font-mono text-xs" />
                  <CopyButton value={webhookUrl} />
                </div>
              </Field>

              <Field
                id="teams-secret"
                label="Jeton de sécurité Teams"
                hint={data.configured ? "Laissez vide pour conserver le jeton actuel (stocké chiffré)." : "Valeur base64 fournie par Teams."}
                required={!data.configured}
              >
                <Input
                  id="teams-secret"
                  type="password"
                  autoComplete="off"
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  placeholder={data.configured ? "••••••••••••" : "Collez le jeton ici"}
                />
              </Field>

              <Field id="teams-app-url" label="URL publique d'ORBIT" hint="Utilisée pour les liens « Continuer dans ORBIT ».">
                <Input id="teams-app-url" value={appUrl} onChange={(e) => setAppUrl(e.target.value)} />
              </Field>

              <div className="flex items-center justify-between rounded-lg border border-border p-3">
                <div>
                  <p className="text-[13px] font-medium">Répondre aux messages Teams</p>
                  <p className="text-xs text-muted-foreground">Désactivez pour suspendre sans perdre la configuration.</p>
                </div>
                <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Répondre aux messages Teams" />
              </div>

              <section aria-label="Comptes reliés" className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-[13px] font-semibold">Comptes reliés</h3>
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setLinks((l) => [...l, { teams_id: "", user_id: "" }])}
                  >
                    <Plus aria-hidden />
                    Ajouter
                  </Button>
                </div>
                {links.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    Sans lien explicite, un message Teams dont l&apos;e-mail correspond à un membre du projet est accepté ;
                    les autres reçoivent « compte non relié ».
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {links.map((link, index) => (
                      <li key={index} className="flex items-center gap-2">
                        <Input
                          aria-label="Identifiant Teams (aadObjectId ou e-mail)"
                          placeholder="aadObjectId ou e-mail"
                          value={link.teams_id}
                          onChange={(e) =>
                            setLinks((l) => l.map((x, i) => (i === index ? { ...x, teams_id: e.target.value } : x)))
                          }
                          className="flex-1"
                        />
                        <Link2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        <SimpleSelect
                          aria-label="Membre ORBIT"
                          value={link.user_id || undefined}
                          onValueChange={(value) =>
                            setLinks((l) => l.map((x, i) => (i === index ? { ...x, user_id: value } : x)))
                          }
                          options={memberOptions}
                          placeholder="Membre…"
                          className="w-48"
                        />
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          aria-label="Retirer ce lien"
                          onClick={() => setLinks((l) => l.filter((_, i) => i !== index))}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          ) : null}
        </SheetBody>
        <SheetFooter>
          {data?.configured ? (
            <Button
              variant="destructive-outline"
              size="sm"
              loading={disconnect.isPending}
              onClick={() =>
                disconnect.mutate(undefined, {
                  onSuccess: () => toast.success("Microsoft Teams est déconnecté"),
                  onError: (e) => toast.error(errorMessage(e)),
                })
              }
              className="mr-auto"
            >
              <Unplug aria-hidden />
              Déconnecter
            </Button>
          ) : null}
          <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
            Fermer
          </Button>
          <Button
            size="sm"
            loading={save.isPending}
            disabled={!data || !data.encryption_available || (!data.configured && !secret.trim())}
            onClick={onSave}
          >
            Enregistrer
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
