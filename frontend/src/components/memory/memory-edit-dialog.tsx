"use client";

import * as React from "react";
import { GitBranch } from "lucide-react";
import { toast } from "sonner";

import { EnumIcon } from "@/components/domain/enum-icon";
import { ClassificationSelect, type ClassificationChoice } from "@/components/sources/classification-select";
import { TagsInput } from "@/components/sources/tags-input";
import { SkillMetaFields, type SkillMetaDraft } from "./skill-meta-fields";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { errorMessage, isApiError } from "@/lib/api/client";
import { useUpdateMemory } from "@/lib/api/hooks";
import type { MemoryItem, MemoryUpdateIn } from "@/lib/api/types";
import { MEMORY_KIND_META, MEMORY_KINDS, type Classification, type MemoryKind } from "@/lib/enums";

import { dateInputToIso, isoToDateInput } from "./memory-dates";

const KIND_OPTIONS = MEMORY_KINDS.map((kind) => ({
  value: kind,
  label: MEMORY_KIND_META[kind].label,
  icon: <EnumIcon name={MEMORY_KIND_META[kind].icon} />,
}));

export interface MemoryEditDialogProps {
  slug: string;
  item: MemoryItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the new version returned by the API. */
  onSaved: (item: MemoryItem) => void;
}

/** Edit dialog: PATCH creates a new version of the lineage (append-only history). */
export function MemoryEditDialog({ slug, item, open, onOpenChange, onSaved }: MemoryEditDialogProps) {
  const [title, setTitle] = React.useState(item.title);
  const [content, setContent] = React.useState(item.content);
  const [kind, setKind] = React.useState<MemoryKind>(item.kind);
  const [classification, setClassification] = React.useState<Classification>(item.classification);
  const [validTo, setValidTo] = React.useState(isoToDateInput(item.valid_to));
  const [tags, setTags] = React.useState<string[]>(item.tags);
  const initialSkill = React.useMemo<SkillMetaDraft>(
    () => ({
      description: item.skill_meta?.description ?? "",
      task_types: item.skill_meta?.task_types ?? [],
      agent_kinds: item.skill_meta?.agent_kinds ?? [],
    }),
    [item.skill_meta],
  );
  const [skillMeta, setSkillMeta] = React.useState<SkillMetaDraft>(initialSkill);
  const update = useUpdateMemory(slug, { meta: { silentError: true } });

  React.useEffect(() => {
    if (!open) return;
    setTitle(item.title);
    setContent(item.content);
    setKind(item.kind);
    setClassification(item.classification);
    setValidTo(isoToDateInput(item.valid_to));
    setTags(item.tags);
    setSkillMeta(initialSkill);
    update.reset();
    // Reset the form each time the dialog opens on a (possibly new) item.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, item.id]);

  const body = React.useMemo<MemoryUpdateIn>(() => {
    const out: MemoryUpdateIn = {};
    if (title.trim() !== item.title) out.title = title.trim();
    if (content.trim() !== item.content.trim()) out.content = content.trim();
    if (kind !== item.kind) out.kind = kind;
    if (classification !== item.classification) out.classification = classification;
    if (validTo !== isoToDateInput(item.valid_to)) out.valid_to = validTo ? dateInputToIso(validTo, "end") : null;
    if (tags.join("\u0000") !== item.tags.join("\u0000")) out.tags = tags;
    if (kind === "procedure" && JSON.stringify(skillMeta) !== JSON.stringify(initialSkill)) {
      out.skill_meta = { ...skillMeta, name: item.skill_meta?.name, description: skillMeta.description.trim() };
    }
    return out;
  }, [title, content, kind, classification, validTo, tags, skillMeta, initialSkill, item]);

  const changed = Object.keys(body).length > 0;
  const fieldErrors = isApiError(update.error) ? update.error.fieldErrors : {};
  const titleError = !title.trim() ? "Le titre est obligatoire." : fieldErrors.title;
  const contentError = !content.trim() ? "Le contenu est obligatoire." : fieldErrors.content;
  const validToError =
    validTo && isoToDateInput(item.valid_from) && validTo < isoToDateInput(item.valid_from)
      ? "La fin de validité doit être postérieure au début."
      : fieldErrors.valid_to;
  const invalid = Boolean(!title.trim() || !content.trim() || validToError);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!changed || invalid) return;
    try {
      const saved = await update.mutateAsync({ id: item.id, body });
      toast.success(`Nouvelle version v${saved.version} enregistrée`, {
        description: "La version précédente est conservée dans l'historique.",
      });
      onSaved(saved);
      onOpenChange(false);
    } catch {
      // Rendered inline below.
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !update.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Modifier l&apos;élément mémoire</DialogTitle>
            <DialogDescription>
              Chaque modification crée une nouvelle version (v{item.version + 1}) ; la version v{item.version} reste
              consultable dans l&apos;historique.
            </DialogDescription>
          </DialogHeader>

          <ClassificationBanner level={classification} compact context="display" />

          <Field id="memory-edit-title" label="Titre" required error={title !== item.title ? titleError : undefined}>
            <Input id="memory-edit-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required />
          </Field>

          <Field
            id="memory-edit-content"
            label="Contenu"
            required
            hint="Markdown accepté (listes, gras, liens)."
            error={content !== item.content ? contentError : undefined}
          >
            <Textarea
              id="memory-edit-content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={8}
              maxLength={20000}
              required
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="memory-edit-kind" label="Nature">
              <SimpleSelect<MemoryKind> id="memory-edit-kind" value={kind} onValueChange={setKind} options={KIND_OPTIONS} />
            </Field>
            <Field id="memory-edit-classification" label="Classification" error={fieldErrors.classification}>
              <ClassificationSelect
                id="memory-edit-classification"
                value={classification}
                onChange={(v: ClassificationChoice) => {
                  if (v !== "auto") setClassification(v);
                }}
              />
            </Field>
            <Field
              id="memory-edit-valid-to"
              label="Fin de validité"
              hint="Laisser vide pour une validité sans échéance."
              error={validToError}
            >
              <Input
                id="memory-edit-valid-to"
                type="date"
                value={validTo}
                min={isoToDateInput(item.valid_from) || undefined}
                onChange={(e) => setValidTo(e.target.value)}
              />
            </Field>
            <Field id="memory-edit-tags" label="Étiquettes">
              <TagsInput id="memory-edit-tags" value={tags} onChange={setTags} />
            </Field>
          </div>

          {kind === "procedure" ? (
            <SkillMetaFields idPrefix="memory-edit" value={skillMeta} onChange={setSkillMeta} />
          ) : null}

          {update.isError ? (
            <Alert tone="red" title="La modification n'a pas pu être enregistrée">
              {errorMessage(update.error)}
            </Alert>
          ) : null}

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={update.isPending}>
              Annuler
            </Button>
            <Button
              type="submit"
              loading={update.isPending}
              disabled={!changed || invalid}
              leftIcon={<GitBranch aria-hidden />}
            >
              Enregistrer la version v{item.version + 1}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
