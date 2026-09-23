"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { FolderPlus } from "lucide-react";
import { toast } from "sonner";

import { projectHref } from "@/components/layout/nav";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage, isApiError } from "@/lib/api/client";
import { useCreateProject } from "@/lib/api/hooks";
import { SLUG_PATTERN, slugify } from "@/lib/utils";

export interface CreateProjectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Navigate to the new project after creation (default true). */
  navigateOnSuccess?: boolean;
}

interface FormErrors {
  name?: string;
  slug?: string;
  description?: string;
  form?: string;
}

const NAME_MAX = 120;
const DESCRIPTION_MAX = 500;

/** "Nouveau projet" dialog → POST /projects (the caller becomes owner). */
export function CreateProjectDialog({ open, onOpenChange, navigateOnSuccess = true }: CreateProjectDialogProps) {
  const router = useRouter();
  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [slugTouched, setSlugTouched] = React.useState(false);
  const [description, setDescription] = React.useState("");
  const [errors, setErrors] = React.useState<FormErrors>({});

  const create = useCreateProject({ meta: { silentError: true } });

  React.useEffect(() => {
    if (!open) {
      setName("");
      setSlug("");
      setSlugTouched(false);
      setDescription("");
      setErrors({});
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the dialog closes
  }, [open]);

  const effectiveSlug = slugTouched ? slug : slugify(name);

  const validate = (): FormErrors => {
    const e: FormErrors = {};
    const n = name.trim();
    if (n.length < 2) e.name = "Le nom doit contenir au moins 2 caractères.";
    else if (n.length > NAME_MAX) e.name = `Le nom ne doit pas dépasser ${NAME_MAX} caractères.`;
    if (effectiveSlug && !SLUG_PATTERN.test(effectiveSlug)) {
      e.slug = "Uniquement des lettres minuscules, chiffres et tirets (ex. projet-atlas).";
    } else if (effectiveSlug.length > 0 && effectiveSlug.length < 2) {
      e.slug = "L'identifiant doit contenir au moins 2 caractères.";
    }
    if (description.length > DESCRIPTION_MAX) e.description = `${DESCRIPTION_MAX} caractères maximum.`;
    return e;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const v = validate();
    setErrors(v);
    if (Object.keys(v).length > 0) return;
    try {
      const project = await create.mutateAsync({
        name: name.trim(),
        ...(effectiveSlug ? { slug: effectiveSlug } : {}),
        ...(description.trim() ? { description: description.trim() } : {}),
      });
      toast.success("Projet créé", { description: `« ${project.name} » est prêt. Vous en êtes propriétaire.` });
      onOpenChange(false);
      if (navigateOnSuccess) router.push(projectHref(project.slug));
    } catch (error) {
      if (isApiError(error)) {
        if (error.isConflict) {
          setErrors({ slug: error.detail || "Cet identifiant est déjà utilisé par un autre projet." });
          setSlugTouched(true);
          setSlug(effectiveSlug);
          return;
        }
        if (error.isValidation) {
          setErrors({
            name: error.fieldErrors.name,
            slug: error.fieldErrors.slug,
            description: error.fieldErrors.description,
            form: !error.fieldErrors.name && !error.fieldErrors.slug && !error.fieldErrors.description ? error.detail : undefined,
          });
          return;
        }
      }
      setErrors({ form: errorMessage(error) });
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              <FolderPlus className="size-5" aria-hidden />
            </div>
            <DialogTitle>Nouveau projet</DialogTitle>
            <DialogDescription>
              Un projet regroupe des sources, une mémoire partagée et des agents. Vous en serez propriétaire.
            </DialogDescription>
          </DialogHeader>

          {errors.form ? <Alert tone="red">{errors.form}</Alert> : null}

          <Field id="project-name" label="Nom du projet" required error={errors.name} labelAside={`${name.length}/${NAME_MAX}`}>
            <Input
              id="project-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (errors.name) setErrors((prev) => ({ ...prev, name: undefined }));
              }}
              placeholder="Ex. Atlas — refonte de l'espace client"
              maxLength={NAME_MAX + 20}
              autoFocus
              required
              invalid={Boolean(errors.name)}
              aria-describedby={fieldDescribedBy("project-name", { error: errors.name })}
            />
          </Field>

          <Field
            id="project-slug"
            label="Identifiant (slug)"
            error={errors.slug}
            hint={
              effectiveSlug ? (
                <>
                  URL : <span className="font-mono">/projects/{effectiveSlug}</span>
                </>
              ) : (
                "Généré automatiquement à partir du nom."
              )
            }
          >
            <Input
              id="project-slug"
              value={effectiveSlug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(e.target.value.toLowerCase().replace(/\s+/g, "-"));
                if (errors.slug) setErrors((prev) => ({ ...prev, slug: undefined }));
              }}
              placeholder="atlas"
              className="font-mono"
              spellCheck={false}
              autoComplete="off"
              invalid={Boolean(errors.slug)}
              aria-describedby={fieldDescribedBy("project-slug", { error: errors.slug, hint: true })}
            />
          </Field>

          <Field
            id="project-description"
            label="Description"
            error={errors.description}
            labelAside={`${description.length}/${DESCRIPTION_MAX}`}
          >
            <Textarea
              id="project-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Objectif, périmètre, équipes concernées…"
              rows={3}
              invalid={Boolean(errors.description)}
              aria-describedby={fieldDescribedBy("project-description", { error: errors.description })}
            />
          </Field>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={create.isPending}>
              Créer le projet
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
