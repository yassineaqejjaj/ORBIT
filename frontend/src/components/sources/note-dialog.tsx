"use client";

import * as React from "react";
import { format } from "date-fns";
import { Eye, NotebookPen, PencilLine } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/client";
import { useCreateTextDocument, useSources } from "@/lib/api/hooks";
import type { DocumentSummary } from "@/lib/api/types";
import { SOURCE_KIND_META, type SourceKind } from "@/lib/enums";
import { formatNumber } from "@/lib/format";
import { AclPicker } from "./acl-picker";
import { aclToPrincipals, DEFAULT_ACL_VALUE, isAclValid, type AclValue } from "./acl";
import { AUTO_CLASSIFICATION, ClassificationSelect, classificationPayload, type ClassificationChoice } from "./classification-select";
import { MarkdownPreview } from "./markdown-preview";
import { DEFAULT_SOURCE, SourceSelect, sourceIdPayload } from "./source-select";
import { NOTE_KINDS, SourceKindSelect } from "./source-kind-select";
import { TagsInput } from "./tags-input";

const TITLE_MAX = 300;
const CONTENT_MAX = 500_000;

const PLACEHOLDERS: Record<SourceKind, string> = {
  note: "## Compte rendu\n\nDécision : …\n\nBesoin : En tant que collaborateur, je veux …\n\nRisque : …",
  ticket: "Description du ticket, critères d'acceptation, étapes de reproduction…",
  crm: "Notes de rendez-vous, interlocuteurs, prochaines étapes…",
  feedback: "Verbatim de l'utilisateur, contexte d'usage, gravité…",
  agent_trace: "Trace d'exécution de l'agent : objectif, étapes, questions ouvertes…",
  document: "Contenu du document en Markdown…",
  url: "Contenu de la page…",
};

function todayInput(): string {
  return format(new Date(), "yyyy-MM-dd");
}

/** "YYYY-MM-DD" (local) → ISO 8601 at local noon (avoids day shifts across time zones). */
function dateInputToIso(value: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const d = new Date(`${value}T12:00:00`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

interface Errors {
  title?: string;
  content?: string;
  date?: string;
  form?: string;
}

export interface NoteDialogProps {
  slug: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultKind?: SourceKind;
  defaultSourceId?: string;
  onCreated?: (document: DocumentSummary) => void;
}

/** "Nouvelle note" — Markdown text ingested through the full pipeline (POST /documents/text). */
export function NoteDialog({ slug, open, onOpenChange, defaultKind = "note", defaultSourceId, onCreated }: NoteDialogProps) {
  const sources = useSources(slug, { enabled: open });
  const create = useCreateTextDocument(slug, { meta: { silentError: true } });

  const [kind, setKind] = React.useState<SourceKind>(defaultKind);
  const [sourceId, setSourceId] = React.useState<string>(defaultSourceId ?? DEFAULT_SOURCE);
  const [title, setTitle] = React.useState("");
  const [author, setAuthor] = React.useState("");
  const [date, setDate] = React.useState(todayInput);
  const [content, setContent] = React.useState("");
  const [mode, setMode] = React.useState<"write" | "preview">("write");
  const [classification, setClassification] = React.useState<ClassificationChoice>(AUTO_CLASSIFICATION);
  const [acl, setAcl] = React.useState<AclValue>(DEFAULT_ACL_VALUE);
  const [aclError, setAclError] = React.useState<string | undefined>();
  const [tags, setTags] = React.useState<string[]>([]);
  const [errors, setErrors] = React.useState<Errors>({});

  React.useEffect(() => {
    if (open) {
      setKind(defaultKind);
      setSourceId(defaultSourceId ?? DEFAULT_SOURCE);
      return;
    }
    setTitle("");
    setAuthor("");
    setDate(todayInput());
    setContent("");
    setMode("write");
    setClassification(AUTO_CLASSIFICATION);
    setAcl(DEFAULT_ACL_VALUE);
    setAclError(undefined);
    setTags([]);
    setErrors({});
    create.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only on open/close
  }, [open, defaultKind, defaultSourceId]);

  // A preselected source drives the kind (once its list is loaded).
  const syncedRef = React.useRef(false);
  React.useEffect(() => {
    if (!open) {
      syncedRef.current = false;
      return;
    }
    if (syncedRef.current || !defaultSourceId || !sources.data) return;
    syncedRef.current = true;
    const source = sources.data.find((s) => s.id === defaultSourceId);
    if (source && NOTE_KINDS.includes(source.kind)) setKind(source.kind);
    else setSourceId(DEFAULT_SOURCE);
  }, [open, defaultSourceId, sources.data]);

  // Keep the selected source consistent with the kind.
  const changeKind = (next: SourceKind) => {
    setKind(next);
    const source = sources.data?.find((s) => s.id === sourceId);
    if (source && source.kind !== next) setSourceId(DEFAULT_SOURCE);
  };

  const level = classificationPayload(classification);

  const validate = (): Errors => {
    const e: Errors = {};
    const t = title.trim();
    if (t.length < 2) e.title = "Le titre doit contenir au moins 2 caractères.";
    else if (t.length > TITLE_MAX) e.title = `${TITLE_MAX} caractères maximum.`;
    if (!content.trim()) e.content = "Le contenu ne peut pas être vide.";
    else if (content.length > CONTENT_MAX) e.content = `${formatNumber(CONTENT_MAX, 0)} caractères maximum.`;
    if (date && !dateInputToIso(date)) e.date = "Date invalide.";
    return e;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const e = validate();
    setErrors(e);
    if (!isAclValid(acl)) setAclError("Sélectionnez au moins un membre autorisé.");
    if (Object.keys(e).length > 0 || !isAclValid(acl)) {
      if (e.content) setMode("write");
      return;
    }
    const explicitSource = sourceIdPayload(sourceId);
    try {
      const doc = await create.mutateAsync({
        ...(explicitSource ? { source_id: explicitSource } : { source_kind: kind }),
        title: title.trim(),
        content,
        author: author.trim() || undefined,
        classification: level,
        acl_principals: aclToPrincipals(acl),
        tags,
        source_updated_at: date ? dateInputToIso(date) : undefined,
      });
      toast.success("Contenu envoyé au pipeline d'ingestion", {
        description: `« ${doc.title} » sera indexé dans quelques secondes.`,
      });
      onCreated?.(doc);
      onOpenChange(false);
    } catch (error) {
      setErrors({ form: errorMessage(error) });
    }
  };

  const busy = create.isPending;

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              <NotebookPen className="size-5" aria-hidden />
            </div>
            <DialogTitle>Nouvelle note</DialogTitle>
            <DialogDescription>
              Compte rendu, ticket, fiche CRM, retour utilisateur ou trace d&apos;agent rédigé en Markdown. Les décisions,
              besoins, contraintes et risques sont extraits automatiquement.
            </DialogDescription>
          </DialogHeader>

          {errors.form ? <Alert tone="red">{errors.form}</Alert> : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="note-kind" label="Type de contenu" required>
              <SourceKindSelect id="note-kind" value={kind} onChange={changeKind} kinds={NOTE_KINDS} disabled={busy} />
            </Field>
            <Field id="note-source" label="Source">
              <SourceSelect
                id="note-source"
                sources={sources.data}
                loading={sources.isPending}
                value={sourceId}
                onChange={setSourceId}
                kinds={[kind]}
                defaultDescription={`Source « ${SOURCE_KIND_META[kind].label} » par défaut (créée si besoin)`}
                disabled={busy}
              />
            </Field>
          </div>

          <Field id="note-title" label="Titre" required error={errors.title} labelAside={`${title.length}/${TITLE_MAX}`}>
            <Input
              id="note-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="CR comité de pilotage du 9 septembre"
              maxLength={TITLE_MAX + 20}
              invalid={Boolean(errors.title)}
              aria-describedby={fieldDescribedBy("note-title", { error: errors.title })}
              disabled={busy}
              autoFocus
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field id="note-date" label="Date métier" hint="Sert au calcul de fraîcheur." error={errors.date}>
              <Input
                id="note-date"
                type="date"
                value={date}
                max={todayInput()}
                onChange={(e) => setDate(e.target.value)}
                invalid={Boolean(errors.date)}
                disabled={busy}
              />
            </Field>
            <Field id="note-author" label="Auteur">
              <Input
                id="note-author"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder="Camille Martin"
                maxLength={200}
                disabled={busy}
              />
            </Field>
            <Field id="note-classification" label="Classification">
              <ClassificationSelect
                id="note-classification"
                value={classification}
                onChange={setClassification}
                allowAuto
                disabled={busy}
              />
            </Field>
          </div>

          {level !== undefined && level >= 2 ? <ClassificationBanner level={level} context="ingest" compact /> : null}

          <Field
            id="note-content"
            label="Contenu (Markdown)"
            required
            error={errors.content}
            labelAside={
              <SegmentedControl<"write" | "preview">
                size="sm"
                value={mode}
                onValueChange={setMode}
                aria-label="Mode d'édition"
                options={[
                  { value: "write", label: "Écrire", icon: <PencilLine aria-hidden /> },
                  { value: "preview", label: "Aperçu", icon: <Eye aria-hidden /> },
                ]}
              />
            }
          >
            {mode === "write" ? (
              <Textarea
                id="note-content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder={PLACEHOLDERS[kind]}
                rows={10}
                invalid={Boolean(errors.content)}
                aria-describedby={fieldDescribedBy("note-content", { error: errors.content })}
                className="font-mono text-[13px]"
                disabled={busy}
              />
            ) : (
              <div className="max-h-72 min-h-40 overflow-y-auto rounded-md border border-border bg-muted/30 px-4 py-3">
                {content.trim() ? (
                  <MarkdownPreview content={content} />
                ) : (
                  <p className="text-[13px] text-muted-foreground">Rien à prévisualiser pour l&apos;instant.</p>
                )}
              </div>
            )}
          </Field>

          <Field id="note-acl" label="Qui peut accéder à ce contenu ?">
            <AclPicker
              slug={slug}
              value={acl}
              onChange={(v) => {
                setAcl(v);
                setAclError(undefined);
              }}
              error={aclError}
              disabled={busy}
              idPrefix="note-acl"
            />
          </Field>

          <Field id="note-tags" label="Étiquettes" hint="Entrée ou virgule pour valider une étiquette.">
            <TagsInput id="note-tags" value={tags} onChange={setTags} disabled={busy} placeholder="pilote-lyon, décision…" />
          </Field>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              Annuler
            </Button>
            <Button type="submit" loading={busy} leftIcon={<NotebookPen aria-hidden />}>
              {busy ? "Envoi…" : "Ingérer la note"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
