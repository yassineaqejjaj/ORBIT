"use client";

import * as React from "react";
import { DatabaseZap, PencilLine } from "lucide-react";
import { toast } from "sonner";

import { useHasRole } from "@/components/auth/require-role";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/client";
import { useCreateSource, useUpdateSource } from "@/lib/api/hooks";
import type { Source } from "@/lib/api/types";
import { DEFAULT_SOURCE_TRUST, SOURCE_TRUST_META, type Classification, type SourceKind, type SourceTrustLevel } from "@/lib/enums";
import { AclPicker } from "./acl-picker";
import { aclToPrincipals, DEFAULT_ACL_VALUE, isAclValid, principalsToAcl, type AclValue } from "./acl";
import { ClassificationSelect, type ClassificationChoice } from "./classification-select";
import { SourceKindSelect } from "./source-kind-select";

const NAME_MAX = 120;
const DESCRIPTION_MAX = 2000;

interface Errors {
  name?: string;
  description?: string;
  form?: string;
}

export interface SourceDialogProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edit this source; create a new one when omitted. */
  source?: Source | null;
  onSaved?: (source: Source) => void;
}

/** Create or edit a business source (name, kind, defaults applied to every ingested document). */
export function SourceDialog({ slug, open, onOpenChange, source, onSaved }: SourceDialogProps) {
  const editing = Boolean(source);
  const create = useCreateSource(slug, { meta: { silentError: true } });
  const update = useUpdateSource(slug, { meta: { silentError: true } });

  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<SourceKind>("document");
  const [description, setDescription] = React.useState("");
  const [classification, setClassification] = React.useState<Classification>(1);
  const [acl, setAcl] = React.useState<AclValue>(DEFAULT_ACL_VALUE);
  const [aclError, setAclError] = React.useState<string | undefined>();
  const [errors, setErrors] = React.useState<Errors>({});
  const isOwner = useHasRole("owner");
  const [trust, setTrust] = React.useState<SourceTrustLevel | "default">("default");

  React.useEffect(() => {
    if (!open) {
      create.reset();
      update.reset();
      return;
    }
    setName(source?.name ?? "");
    setKind(source?.kind ?? "document");
    setDescription(source?.description ?? "");
    setClassification(source?.default_classification ?? 1);
    setAcl(source ? principalsToAcl(source.default_acl) : DEFAULT_ACL_VALUE);
    setAclError(undefined);
    setTrust(source?.trust ?? "default");
    setErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initialize when the dialog opens
  }, [open, source]);

  const busy = create.isPending || update.isPending;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const e: Errors = {};
    const n = name.trim();
    if (n.length < 2) e.name = "Le nom doit contenir au moins 2 caractères.";
    else if (n.length > NAME_MAX) e.name = `${NAME_MAX} caractères maximum.`;
    if (description.length > DESCRIPTION_MAX) e.description = `${DESCRIPTION_MAX} caractères maximum.`;
    setErrors(e);
    const aclOk = isAclValid(acl);
    if (!aclOk) setAclError("Sélectionnez au moins un membre autorisé.");
    if (Object.keys(e).length > 0 || !aclOk) return;

    const body = {
      name: n,
      kind,
      description: description.trim(),
      default_classification: classification,
      default_acl: aclToPrincipals(acl),
      ...(isOwner && trust !== "default" && trust !== source?.trust ? { trust } : {}),
    };
    try {
      const saved = source ? await update.mutateAsync({ id: source.id, body }) : await create.mutateAsync(body);
      toast.success(source ? "Source mise à jour" : "Source créée", { description: saved.name });
      onSaved?.(saved);
      onOpenChange(false);
    } catch (error) {
      setErrors({ form: errorMessage(error) });
    }
  };

  const onClassification = (choice: ClassificationChoice) => {
    if (choice !== "auto") setClassification(choice);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              {editing ? <PencilLine className="size-5" aria-hidden /> : <DatabaseZap className="size-5" aria-hidden />}
            </div>
            <DialogTitle>{editing ? "Modifier la source" : "Nouvelle source"}</DialogTitle>
            <DialogDescription>
              Une source regroupe des contenus de même nature (comptes rendus, tickets Jira, CRM…). Sa classification et ses
              droits par défaut s&apos;appliquent à chaque document ingéré.
            </DialogDescription>
          </DialogHeader>

          {errors.form ? <Alert tone="red">{errors.form}</Alert> : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="source-name" label="Nom" required error={errors.name}>
              <Input
                id="source-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Comptes rendus de comité"
                invalid={Boolean(errors.name)}
                aria-describedby={fieldDescribedBy("source-name", { error: errors.name })}
                maxLength={NAME_MAX + 10}
                disabled={busy}
                autoFocus
              />
            </Field>
            <Field id="source-kind" label="Type" required hint={editing ? "Le type détermine la politique de fraîcheur." : undefined}>
              <SourceKindSelect id="source-kind" value={kind} onChange={setKind} disabled={busy} />
            </Field>
          </div>

          <Field id="source-description" label="Description" error={errors.description}>
            <Textarea
              id="source-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Origine des contenus, périmètre, responsable…"
              rows={3}
              invalid={Boolean(errors.description)}
              disabled={busy}
            />
          </Field>

          <Field
            id="source-classification"
            label="Classification par défaut"
            hint="Le pipeline peut relever le niveau d'un document (mots-clés sensibles, données personnelles), jamais l'abaisser."
          >
            <ClassificationSelect id="source-classification" value={classification} onChange={onClassification} disabled={busy} />
          </Field>

          {isOwner ? (
            <Field
              id="source-trust"
              label="Confiance"
              hint="Pondère le classement et la promotion en mémoire (sécurité IA). Réservé aux propriétaires."
            >
              <SimpleSelect
                id="source-trust"
                value={trust}
                onValueChange={setTrust}
                disabled={busy}
                options={[
                  {
                    value: "default",
                    label: `Par défaut du type (${SOURCE_TRUST_META[DEFAULT_SOURCE_TRUST[kind]].label.toLowerCase()})`,
                  },
                  ...(["high", "medium", "low"] as const).map((level) => ({
                    value: level,
                    label: SOURCE_TRUST_META[level].label,
                    description: SOURCE_TRUST_META[level].description,
                  })),
                ]}
              />
            </Field>
          ) : null}

          <Field id="source-acl" label="Accès par défaut">
            <AclPicker
              slug={slug}
              value={acl}
              onChange={(v) => {
                setAcl(v);
                setAclError(undefined);
              }}
              error={aclError}
              disabled={busy}
              idPrefix="source-acl"
            />
          </Field>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              Annuler
            </Button>
            <Button type="submit" loading={busy}>
              {editing ? "Enregistrer" : "Créer la source"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
