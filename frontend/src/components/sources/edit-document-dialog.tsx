"use client";

import * as React from "react";
import { PencilLine } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api/client";
import { useUpdateDocument } from "@/lib/api/hooks";
import type { DocumentSummary, DocumentUpdateIn } from "@/lib/api/types";
import { toClassification, type Classification } from "@/lib/enums";
import { AclPicker } from "./acl-picker";
import { aclToPrincipals, isAclValid, principalsToAcl, type AclValue } from "./acl";
import { ClassificationSelect, type ClassificationChoice } from "./classification-select";
import { TagsInput } from "./tags-input";

const TITLE_MAX = 300;

function sameList(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.every((v, i) => v === sb[i]);
}

export interface EditDocumentDialogProps {
  slug: string;
  document: DocumentSummary;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** "Modifier" — title, classification, ACL and tags (PATCH /documents/{id}; metadata re-indexed, audited). */
export function EditDocumentDialog({ slug, document, open, onOpenChange }: EditDocumentDialogProps) {
  const update = useUpdateDocument(slug, { meta: { silentError: true } });
  const [title, setTitle] = React.useState(document.title);
  const [classification, setClassification] = React.useState<Classification>(toClassification(document.classification));
  const [acl, setAcl] = React.useState<AclValue>(principalsToAcl(document.acl_principals));
  const [tags, setTags] = React.useState<string[]>(document.tags);
  const [titleError, setTitleError] = React.useState<string | undefined>();
  const [aclError, setAclError] = React.useState<string | undefined>();
  const [formError, setFormError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) {
      update.reset();
      return;
    }
    setTitle(document.title);
    setClassification(toClassification(document.classification));
    setAcl(principalsToAcl(document.acl_principals));
    setTags(document.tags);
    setTitleError(undefined);
    setAclError(undefined);
    setFormError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initialize when the dialog opens
  }, [open, document]);

  const lowered = classification < document.classification;
  const busy = update.isPending;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const t = title.trim();
    let invalid = false;
    if (t.length < 2 || t.length > TITLE_MAX) {
      setTitleError(t.length < 2 ? "Le titre doit contenir au moins 2 caractères." : `${TITLE_MAX} caractères maximum.`);
      invalid = true;
    }
    if (!isAclValid(acl)) {
      setAclError("Sélectionnez au moins un membre autorisé.");
      invalid = true;
    }
    if (invalid) return;

    const principals = aclToPrincipals(acl);
    const body: DocumentUpdateIn = {};
    if (t !== document.title) body.title = t;
    if (classification !== document.classification) body.classification = classification;
    if (!sameList(principals, document.acl_principals)) body.acl_principals = principals;
    if (!sameList(tags, document.tags)) body.tags = tags;
    if (Object.keys(body).length === 0) {
      onOpenChange(false);
      return;
    }
    try {
      await update.mutateAsync({ id: document.id, body });
      toast.success("Document mis à jour", {
        description:
          body.classification !== undefined || body.acl_principals
            ? "Droits et classification propagés aux extraits indexés. Modification journalisée dans l'audit."
            : "Modification journalisée dans l'audit.",
      });
      onOpenChange(false);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              <PencilLine className="size-5" aria-hidden />
            </div>
            <DialogTitle>Modifier le document</DialogTitle>
            <DialogDescription>
              Les changements de classification et de droits sont appliqués aux extraits indexés et à la mémoire dérivée, et
              journalisés dans l&apos;audit.
            </DialogDescription>
          </DialogHeader>

          {formError ? <Alert tone="red">{formError}</Alert> : null}

          <Field id="edit-doc-title" label="Titre" required error={titleError}>
            <Input
              id="edit-doc-title"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                setTitleError(undefined);
              }}
              invalid={Boolean(titleError)}
              aria-describedby={fieldDescribedBy("edit-doc-title", { error: titleError })}
              maxLength={TITLE_MAX + 20}
              disabled={busy}
            />
          </Field>

          <Field id="edit-doc-classification" label="Classification">
            <ClassificationSelect
              id="edit-doc-classification"
              value={classification}
              onChange={(c: ClassificationChoice) => {
                if (c !== "auto") setClassification(c);
              }}
              disabled={busy}
            />
          </Field>
          {lowered ? (
            <Alert tone="amber" title="Déclassification">
              Vous abaissez la classification de ce document : vérifiez qu&apos;il ne contient plus d&apos;informations sensibles.
              Le contenu deviendra accessible aux personnes et agents moins habilités.
            </Alert>
          ) : null}
          {classification >= 2 ? <ClassificationBanner level={classification} compact /> : null}

          <Field id="edit-doc-acl" label="Qui peut accéder à ce document ?">
            <AclPicker
              slug={slug}
              value={acl}
              onChange={(v) => {
                setAcl(v);
                setAclError(undefined);
              }}
              error={aclError}
              disabled={busy}
              idPrefix="edit-doc-acl"
            />
          </Field>

          <Field id="edit-doc-tags" label="Étiquettes">
            <TagsInput id="edit-doc-tags" value={tags} onChange={setTags} disabled={busy} />
          </Field>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              Annuler
            </Button>
            <Button type="submit" loading={busy}>
              Enregistrer
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
